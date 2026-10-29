from collections import Counter
from difflib import get_close_matches
from functools import reduce
from operator import and_, or_

from django.apps import apps
from django.db.models import ForeignKey, Q

from syncope.models import CustomUser

APP_LABEL = "syncope"
SKIP = {"Invitation", "Share", "ShareVisit"}
VERSION = 6
SECTIONS = ("schema", "fixtures", "data")
FIXTURE_IGNORED = {"id", "created_at", "updated_at", "additional_notes"}  # not part of what a fixture row means


class BackupError(Exception):
    """A problem at one row of the backup. str() is the server log text, `message` what the user sees (with a row hint)."""

    def __init__(self, where, reason, label=""):
        super().__init__(f"{where}: {reason}")
        self.message = f"{where}{f' ({label})' if label else ''}: {reason}"


def row_label(row):
    """A short hint for a backup row: its first text value."""
    return next((v[:40] for k, v in row.items() if isinstance(v, str) and v and not k.endswith("_at")), "")


def fixture_label(row):
    """What a fixed value is called: its values without ids, stamps and notes."""
    return " ".join(str(v) for k, v in row.items() if k not in FIXTURE_IGNORED and v not in (None, ""))


def resolve(ids, file_target, field, value):
    """New id for a source FK value, or None. A link whose target model changed since the file was made is not remapped."""
    if file_target != field.related_model.__name__:
        return None
    return ids.get(file_target, {}).get(str(value))


def _fks(model):
    return [f for f in model._meta.concrete_fields if isinstance(f, ForeignKey)]


def user_fks(model):
    """Ownership FKs: rows pointing at the org account. Not exported, the importer sets them."""
    return [f for f in _fks(model) if f.related_model is CustomUser]


def _follow(model):
    """FKs that link to other exported rows: not the user, not self (Person.owner would pull in personal profiles)."""
    return [f for f in _fks(model) if f.related_model not in (CustomUser, model)]


def export_fields(model):
    """Exported fields: not the user FK (importer sets it) and not self FKs (Person.owner)."""
    skip = {f.attname for f in user_fks(model)} | {f.attname for f in _fks(model) if f.related_model is model}
    return [f for f in model._meta.concrete_fields if f.attname not in skip]


def _rows(qs):
    cols = export_fields(qs.model)
    # "id" is always the row's pk, also for models with a natural pk (LanguageCode.language_code)
    return [{"id": obj.pk} | {f.attname: getattr(obj, f.attname) for f in cols} for obj in qs.order_by("pk")]


def _models():
    """(fixtures, data): fixtures have no FKs, data is everything else that stays inside the app."""
    models = [m for m in apps.get_app_config(APP_LABEL).get_models(include_auto_created=True)
              if m is not CustomUser and m.__name__ not in SKIP]
    fixtures = [m for m in models if not _fks(m)]
    # FKs leaving the app (CustomUser_groups -> auth.Group) are not ours
    data = [m for m in models if m not in fixtures and all(f.related_model._meta.app_label == APP_LABEL for f in _fks(m))]
    return fixtures, data


def export_schema():
    """Every exported model: its fields and which of them are FKs (to remap on import) with their target model."""
    fixtures, data = _models()
    schema = {}
    for kind, group in (("fixture", fixtures), ("data", data)):
        for m in group:
            fields = export_fields(m)
            schema[m.__name__] = {
                "kind": kind,
                "fields": [f.attname for f in fields],
                "fks": {f.attname: f.related_model.__name__ for f in fields if isinstance(f, ForeignKey)},
            }
    return schema


def fixture_keys():
    """Fields that identify a fixed value across servers: its unique non-pk fields (Role.title); none for some."""
    return {m.__name__: [f.attname for f in export_fields(m) if f.unique and not f.primary_key] for m in _models()[0]}


def export_fixtures():
    return {m.__name__: _rows(m.objects.all()) for m in _models()[0]}


def export_org(org_user):
    """
    Everything under org_user, read from the models so new fields and models need no change here.
    One flat list per model, FKs as source ids; the importer remaps them.
    """
    data = _models()[1]

    pks = {m: set() for m in data}
    for m in data:  # rows the org owns directly
        if user_fks(m):
            q = reduce(or_, (Q(**{f.name: org_user}) for f in user_fks(m)))
            pks[m] = set(m.objects.filter(q).values_list("pk", flat=True))

    size = -1
    while size != sum(map(len, pks.values())):  # until a pass adds nothing
        size = sum(map(len, pks.values()))
        for m in data:
            for f in _follow(m):  # parents of what we have (Membership -> Person)
                if f.related_model in pks:
                    pks[f.related_model] |= set(
                        m.objects.filter(pk__in=pks[m]).exclude(**{f.attname: None}).values_list(f.attname, flat=True))
            if not user_fks(m):  # children of what we have (Event -> Attendance), all their parents must be ours
                fks = [f for f in _follow(m) if f.related_model in pks]
                if fks:
                    inside = [Q(**{f"{f.attname}__in": pks[f.related_model]}) for f in fks]
                    empty = [Q(**{f"{f.attname}__isnull": True}) for f in fks]
                    q = reduce(or_, inside) & reduce(and_, (i | e for i, e in zip(inside, empty)))
                    pks[m] |= set(m.objects.filter(q).values_list("pk", flat=True))

    return {
        "version": VERSION,
        "schema": export_schema(),
        "fixtures": export_fixtures(),
        "data": {m.__name__: _rows(m.objects.filter(pk__in=pks[m])) for m in data},
    }


def allowlist(payload):
    """The file is untrusted: keep only models this server exports itself. Returns the cleaned payload and the dropped names."""
    known = export_schema()
    dropped = sorted({name for key in SECTIONS for name in payload[key]} - known.keys())
    return {"version": payload.get("version")} | {key: {n: v for n, v in payload[key].items() if n in known}
                                                  for key in SECTIONS}, dropped


def diff_schema(src, dst):
    """
    Per model present on both sides: source fields that are gone here (with a guess at the renamed field here)
    and fields that are new here. Models and fields that are the same are left out.
    """
    out = {}
    for model in src.keys() & dst.keys():
        gone = [f for f in src[model]["fields"] if f not in dst[model]["fields"]]
        new = [f for f in dst[model]["fields"] if f not in src[model]["fields"]]
        fk_changed = {f: (src[model]["fks"].get(f), dst[model]["fks"].get(f)) for f in src[model]["fields"]
                      if f in dst[model]["fields"] and src[model]["fks"].get(f) != dst[model]["fks"].get(f)}
        if gone or new or fk_changed:
            out[model] = {
                "gone": {f: (get_close_matches(f, new, 1, 0.6) or [None])[0] for f in gone},
                "new": new,
                "fk_changed": fk_changed,
            }
    return out


def diff_fixtures(src, dst, identity=None):
    """
    Per fixture model: source rows that equal a row here (the pk may have moved) are mapped, the rest are left for the
    user, each with the closest row here as a guess. Rows are compared by their `identity` fields (unique name) when both
    sides have them, else by every shared field except ids, stamps and notes.
    """
    out = {}
    for model in src.keys() & dst.keys():
        if not src[model]:
            continue
        shared = set(src[model][0]) & set(dst[model][0]) if dst[model] else set()
        keys = [k for k in (identity or {}).get(model, []) if k in shared] or sorted(shared - FIXTURE_IGNORED)
        here = {tuple(r[k] for k in keys): r["id"] for r in reversed(dst[model])}  # lowest id wins a duplicate
        names = {" ".join(map(str, key)): pk for key, pk in here.items()}
        mapped, unmapped, guess = {}, [], {}
        for row in src[model]:
            match = here.get(tuple(row[k] for k in keys))
            if match is not None:
                mapped[str(row["id"])] = match
                continue
            unmapped.append(row)
            near = get_close_matches(" ".join(str(row[k]) for k in keys), names, 1, 0.6)
            if near:
                guess[str(row["id"])] = names[near[0]]
        out[model] = {"mapped": mapped, "unmapped": unmapped, "options": dst[model], "guess": guess}
    return out


def fixture_usage(data, fixtures, src_schema, dst_schema):
    """
    Which data fields point at each unmapped fixed value: {model: {source id: {"refs": {"Singer.voice_id": 3}, "none_ok": bool}}}.
    A value nobody points at has no entry. none_ok: every field using it may be empty on this server.
    """
    out = {}
    for model, d in fixtures.items():
        refs = {str(r["id"]): Counter() for r in d["unmapped"]}
        for name, rows in data.items():
            for key, target in src_schema[name]["fks"].items():
                if target == model and dst_schema[name]["fks"].get(key) == model:
                    for row in rows:
                        if str(row.get(key)) in refs:
                            refs[str(row[key])][(name, key)] += 1
        out[model] = {i: {"refs": {f"{n}.{k}": c for (n, k), c in used.items()},
                          "none_ok": all(apps.get_model(APP_LABEL, n)._meta.get_field(k).null for n, k in used)}
                      for i, used in refs.items() if used}
    return out


def check_shape(payload):
    """What is structurally wrong with an uploaded backup, located (at most 10). Empty when it can be read."""
    problems = []
    for section in ("fixtures", "data"):
        for model, rows in payload[section].items():
            if not isinstance(rows, list):
                problems.append(f"{section}.{model} is not a list")
                continue
            problems += [f"{section}.{model}[{i}] is not a row with an id" for i, r in enumerate(rows)
                         if not (isinstance(r, dict) and "id" in r)]
            if model not in payload["schema"]:
                problems.append(f"{section}.{model} has no entry in schema")
    problems += [f"schema.{model} lacks fields or fks" for model, e in payload["schema"].items()
                 if not (isinstance(e, dict) and isinstance(e.get("fields"), list) and isinstance(e.get("fks"), dict))]
    orgs = payload["data"].get("Organization")
    if not isinstance(orgs, list) or len(orgs) != 1:
        problems.append(f"the backup must hold exactly one organization, it has {len(orgs) if isinstance(orgs, list) else 0}")
    else:
        problems += [f"data.Organization[0] has no {k}" for k in ("name", "email")
                     if isinstance(orgs[0], dict) and not (isinstance(orgs[0].get(k), str) and orgs[0][k])]
    return problems[:10]

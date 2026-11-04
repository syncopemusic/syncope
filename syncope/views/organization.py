import json
import logging
import os
import tempfile
import time
from collections import Counter
from pathlib import Path
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.db.models import Q
from datetime import datetime
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, UpdateView, View
import datetime
from django.views.generic import TemplateView
from django.apps import apps
from django.db import DatabaseError, transaction
from django.db.models import ForeignKey, UniqueConstraint
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.text import Truncator
from syncope.models import (
    MembershipPeriod, PersonRole, EventSongResource, ProjectResource, ShareVisit,
    PersonSkill, Singer, Instrumentalist, PersonResource,
    CustomUser, Organization, Person, Membership, Role, Song, Event, Project, Poll, Share
)
from syncope.forms import OrganizationForm
from syncope.backup import (
    APP_LABEL, SECTIONS, VERSION, BackupError, allowlist, check_shape, diff_fixtures, diff_schema, export_fields,
    export_fixtures, export_org, export_schema, org_pks, fixture_keys, fixture_label, fixture_usage, resolve, row_label, user_fks,
)
from syncope.permissions import AccessControl
from syncope.views.drafts import DraftMixin

logger = logging.getLogger(__name__)


class OrgAdminMixin:
    """Resolves org from URL kwarg and restricts access to ADMIN role members."""

    def get_object(self, queryset=None):
        return get_object_or_404(
            Organization.objects.select_related('user'),
            user__username=self.kwargs['username'],
        )

    def dispatch(self, request, *args, **kwargs):
        roles = AccessControl.get_org_roles(request.user, self.kwargs['username'])
        if not roles.filter(id=Role.ADMIN).exists():
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)


@method_decorator(login_required, name='dispatch')
class OrganizationDashboard(TemplateView):
    """Home page for specific organizations."""
    template_name = "syncope/org_dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs["username"]

        # a personal account has no Organization row: its dashboard is the user's home
        if request.user.is_authenticated and request.user.username == url_username \
                and not Organization.objects.filter(user=request.user).exists():
            self.template_name = "syncope/user_dashboard.html"
            self.organization = None
            return TemplateView.dispatch(self, request, *args, **kwargs)

        self.organization = get_object_or_404(
            Organization,
            user__username=url_username
        )

        self.viewer_roles = AccessControl.get_org_roles(
            request.user,
            url_username
        )

        if not self.viewer_roles:
            return HttpResponseForbidden()

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.organization is None:
            return context  # user dashboard: the context processor already supplies everything
        context["organization"] = self.organization
        context["url_username"] = self.kwargs["username"]
        context["is_admin"] = self.viewer_roles.filter(id=Role.ADMIN).exists()
        context["is_supporter"] = self.viewer_roles.filter(id=Role.SUPPORTER).exists()
        context["can_view_org"] = self.viewer_roles.filter(id__in=[Role.ADMIN, Role.MEMBER]).exists()  # same rule as the side menu

        context["org_memberships"] = AccessControl.get_visible_members(
            self.request.user,
            self.kwargs["username"]
        )

        return context


def create_org_account(slug, email):
    """Login account of a new organization, `slug` is its URL name. Call inside a transaction."""
    org_user = CustomUser.objects.create(username=slug, email=email)
    org_user.set_unusable_password()
    org_user.save()
    return org_user


def make_org_admin(org_user, the_admin):
    """the_admin becomes ADMIN of the org, as a copy of their profile. Call inside a transaction."""
    transfer_fields = [
        "first_name", "last_name", "email", "address", "phone",
        "birth_date", "birth_approximate", "death_date", "death_approximate",
    ]
    person = Person.objects.create(
        owner=the_admin,
        **{field: getattr(the_admin, field) for field in transfer_fields}
    )

    # copy skills, voices, instruments
    skill_ids = PersonSkill.objects.filter(person=the_admin).values_list("skill_id", flat=True)
    voice_ids = Singer.objects.filter(person=the_admin).values_list("voice_id", flat=True)
    instrument_ids = Instrumentalist.objects.filter(person=the_admin).values_list("instrument_id", flat=True)

    PersonSkill.objects.bulk_create([
        PersonSkill(person=person, skill_id=sid) for sid in skill_ids
    ], ignore_conflicts=True)
    Singer.objects.bulk_create([
        Singer(person=person, voice_id=vid) for vid in voice_ids
    ], ignore_conflicts=True)
    Instrumentalist.objects.bulk_create([
        Instrumentalist(person=person, instrument_id=iid) for iid in instrument_ids
    ], ignore_conflicts=True)

    # copy person resources (portfolio)
    human_resources = PersonResource.objects.filter(person=the_admin).values_list('resource_id', 'order')
    PersonResource.objects.bulk_create([
        PersonResource(person=person, resource_id=resource_id, order=order)
        for resource_id, order in human_resources
    ], ignore_conflicts=True)

    Membership.objects.get_or_create(user=org_user, person=person)
    PersonRole.objects.get_or_create(person=person, role_id=Role.ADMIN)
    if not MembershipPeriod.objects.filter(user=org_user, person=person, role_id=Role.ADMIN, ended_at=None).exists():
        MembershipPeriod.objects.create(
            user=org_user,
            person=person,
            role_id=Role.ADMIN,
            started_at=datetime.date.today()
        )


@method_decorator(login_required, name='dispatch')
class OrganizationCreateView(DraftMixin, CreateView):
    template_name = "syncope/org_form.html"
    form_class = OrganizationForm
    context_object_name = "org_create"
    success_url = reverse_lazy("syncope:home")

    def form_valid(self, form):
        with transaction.atomic():
            organization = form.save(commit=False)
            organization.user = create_org_account(form.cleaned_data["slug"], organization.email)
            organization.save()
            make_org_admin(organization.user, Person.objects.filter(user=self.request.user).first())

        return super().form_valid(form)


@method_decorator(login_required, name='dispatch')
class OrganizationUpdateView(OrgAdminMixin, UpdateView):  # no drafts: a rejected value must not replace the current one
    model = Organization
    form_class = OrganizationForm
    template_name = "syncope/org_form.html"

    def get_success_url(self):
        # stay on the edit page; the slug may just have changed, so build the URL again
        url = reverse("syncope:org_edit", kwargs={"username": self.object.user.username})
        query = self.request.META.get("QUERY_STRING")
        return f"{url}?{query}" if query else url

    def form_valid(self, form):
        with transaction.atomic():  # the login account follows the organization's email and slug
            user = form.instance.user
            user.email = form.cleaned_data["email"]
            user.username = form.cleaned_data["slug"]
            user.save(update_fields=["email", "username"])
            response = super().form_valid(form)
        messages.success(self.request, "Organization updated successfully!")
        return response


@method_decorator(login_required, name='dispatch')
class OrganizationDeleteView(OrgAdminMixin, DeleteView):
    model = Organization
    template_name = "syncope/org_confirm_delete.html"
    success_url = reverse_lazy("syncope:home")


    def delete_object(self, queryset=None):
        org_user = self.object.user

        with transaction.atomic():
            # Delete PROTECT-guarded junction tables first to unblock the cascade
            EventSongResource.objects.filter(
                Q(event_song__event__user=org_user) | Q(resource__owner=org_user)
            ).delete()
            ProjectResource.objects.filter(resource__owner=org_user).delete()

            # Capture person IDs before memberships are gone
            orphaned_person_ids = list(
                Person.objects.filter(memberships__user=org_user, user=None)
                .values_list('id', flat=True)
            )

            # Delete ShareVisit rows that would block cascade (PROTECT constraint)
            ShareVisit.objects.filter(
                Q(share__resource__owner=org_user) |
                Q(share__event__user=org_user) |
                Q(share__project__user=org_user) |
                Q(share__poll__user=org_user) |
                Q(share__song__user=org_user) |
                Q(share__poll_person__poll__user=org_user) |
                Q(share__person__id__in=orphaned_person_ids)
            ).delete()

            # Explicitly delete memberships (persons with user=None are not reached by org_user cascade)
            MembershipPeriod.objects.filter(user=org_user).delete()
            Membership.objects.filter(user=org_user).delete()

            # Delete the orphaned persons themselves
            Person.objects.filter(id__in=orphaned_person_ids).delete()

            # Delete the organization
            self.object.delete()

            # Delete the CustomUser - must be done explicitly since the FK is ON Organization
            # pointing TO CustomUser, so cascade doesn't work in reverse
            org_user.delete()

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        org_name = self.object.name
        self.delete_object()
        messages.success(request, f"Organization '{org_name}' has been deleted.")
        return HttpResponseRedirect(self.success_url)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs['username']
        context['is_admin'] = True
        return context


@method_decorator(login_required, name="dispatch")
class OrgBackupView(OrgAdminMixin, View):
    """Backup file into an existing org: upload, review what differs from this server, confirm. ADMIN only."""
    template_name = "syncope/org_backup.html"
    SESSION_KEY = "org_backup"
    SAMPLE_ROWS = 3
    SAMPLE_CHARS = 80
    ADMIN_LINKS = ("Membership", "PersonRole", "MembershipPeriod")  # the admin person already has these

    @cached_property
    def org_user(self):
        return self.get_object().user

    def get(self, request, username):
        return render(request, self.template_name, {"url_username": username,
                                                    "result": request.session.pop("org_backup_result", None)})

    def forget(self, request):
        saved = request.session.pop(self.SESSION_KEY, None)
        if saved and os.path.exists(saved["path"]):
            os.remove(saved["path"])

    def reject(self, request, message):
        logger.warning("org backup rejected (user=%s): %s", request.user, message)
        messages.error(request, message)
        return redirect("syncope:org_import_backup", username=self.org_user.username)

    def diffs(self, payload):
        """What differs between the file and this server: (fixtures, schema)."""
        return (diff_fixtures(payload["fixtures"], export_fixtures(), fixture_keys()),
                diff_schema(payload["schema"], export_schema()))

    def stats(self, payload):
        """What is in the file: rows per model, file against what the org holds now."""
        now = {m.__name__: len(pks) for m, pks in org_pks(self.org_user).items()}
        return [{"model": model, "file": len(rows), "now": now.get(model, 0)}
                for model, rows in payload["data"].items() if model != "Organization"]

    def samples(self, payload):
        """The first rows of every model in the file, cut short, so the page stays small whatever the file size."""
        def cell(value):
            return "" if value is None else Truncator(str(value)).chars(self.SAMPLE_CHARS)
        return [{"model": model, "fields": list(rows[0]),
                 "rows": [[cell(v) for v in row.values()] for row in rows[:self.SAMPLE_ROWS]]}
                for section in ("fixtures", "data") for model, rows in payload[section].items() if rows]

    def owner(self, model):
        """Ownership FKs of a new row. Person.user is a login link, not ownership."""
        return {} if model is Person else {f.attname: self.org_user.pk for f in user_fks(model)}

    def clashes(self, name, rows, cols, renames, skip):
        """Rows of one model that fail its validation, grouped by field and bad value (FKs wait for their new ids)."""
        model = apps.get_model(APP_LABEL, name)
        back = {new: old for old, new in renames.items()}
        plain = {a for a, f in cols.items() if not isinstance(f, ForeignKey) and not f.primary_key}
        groups = {}
        for src in rows:
            if skip(name, src):
                continue
            kwargs = {a: v for k, v in src.items() if (a := renames.get(k, k)) in plain}
            exclude = [f.name for a, f in cols.items() if a not in kwargs]  # FKs and fields the file lacks
            try:  # ponytail: a few queries per row (owner FK, unique checks), batch if big files get slow
                model(**self.owner(model), **kwargs).full_clean(exclude=exclude)
            except ValidationError as e:
                for field, messages in e.message_dict.items():
                    key = back.get(field, field)
                    group = groups.setdefault((name, key, str(src.get(key))), {"message": messages[0], "rows": []})
                    group["rows"].append((src["id"], row_label(src)))
        return [{"model": n, "field": k, "value": v, "fixable": k != "__all__", **g} for (n, k, v), g in groups.items()]

    def review(self, request, payload, dropped, errors=(), clashes=(), existing=()):
        """The review page: how the file differs from this server, and the errors of a failed import if any."""
        fixtures, schema = self.diffs(payload)
        usage = fixture_usage(payload["data"], fixtures, payload["schema"], export_schema())
        fixture_diff = {}
        for model, d in fixtures.items():
            used = usage.get(model, {})
            rows = [{
                "id": row["id"],
                "label": fixture_label(row),
                "refs": ", ".join(f"{field} ({n})" for field, n in used[str(row["id"])]["refs"].items()),
                "none_ok": used[str(row["id"])]["none_ok"],
                "guess": d["guess"].get(str(row["id"])),
            } for row in d["unmapped"] if str(row["id"]) in used]
            if rows:
                fixture_diff[model] = {"rows": rows,
                                       "options": [{"id": r["id"], "label": fixture_label(r)} for r in d["options"]]}
        return render(request, self.template_name, {
            "reviewing": True,
            "url_username": self.org_user.username,
            "file_size": os.path.getsize(request.session[self.SESSION_KEY]["path"]),
            "stats": self.stats(payload),
            "samples": self.samples(payload),
            "errors": errors,
            "clashes": clashes,
            "existing": existing,
            "schema_diff": schema,
            "fixture_diff": fixture_diff,
            "dropped": dropped,
            "compared": sorted(fixtures),
            "file_version": payload.get("version"),
            "file_exported_at": payload.get("exported_at"),
            "version": VERSION,
            "no_differences": not (schema or dropped or fixture_diff),
        })

    def post(self, request, username):
        if "file" in request.FILES:  # step 1: upload and review
            upload = request.FILES["file"]
            try:
                payload = json.load(upload)
            except ValueError as e:  # includes bad encoding, e.g. a zip uploaded as is
                return self.reject(request, f"The file is not valid JSON ({e}). If it is a zip, extract it first.")
            if not isinstance(payload, dict):
                return self.reject(request, "The file is JSON but not a Syncope backup (expected an object at the top).")
            missing = [k for k in SECTIONS if not isinstance(payload.get(k), dict)]
            if missing:
                return self.reject(request, f"Not a usable backup, missing: {', '.join(missing)} "
                                            f"(backup version {payload.get('version')}). Export it again.")
            problems = check_shape(payload)
            if problems:
                return self.reject(request, "The backup is malformed: " + "; ".join(problems) + ".")
            try:
                payload, dropped = allowlist(payload)
                self.forget(request)
                for old in Path(tempfile.gettempdir()).glob("syncope-backup-*.json"):  # abandoned uploads
                    if time.time() - old.stat().st_mtime > 7200:
                        old.unlink(missing_ok=True)
                with tempfile.NamedTemporaryFile("w", delete=False, prefix="syncope-backup-", suffix=".json",
                                                 encoding="utf-8") as tmp:
                    json.dump(payload, tmp)
                request.session[self.SESSION_KEY] = {"path": tmp.name, "dropped": dropped, "name": upload.name,
                                                     "org": username}
                return self.review(request, payload, dropped)
            except Exception:
                logger.exception("org backup upload crashed (user=%s file=%s)", request.user, upload.name)
                return self.reject(request, "Unexpected error while reading the backup, details are in the server log.")

        # step 2: the user's choices, then import
        saved = request.session.get(self.SESSION_KEY)
        if not saved or saved.get("org") != username or not os.path.exists(saved["path"]):
            return self.reject(request, "Upload the backup file again.")
        with open(saved["path"], encoding="utf-8") as f:  # not read_text: that holds the whole file twice
            payload = json.load(f)
        dropped = saved["dropped"]
        who = f"user={request.user} file={saved.get('name')}"
        try:
            the_admin = AccessControl.get_auth_person(request.user)
        except Person.DoesNotExist:
            return self.review(request, payload, dropped, ["You have no personal profile yet."])
        fixtures, schema = self.diffs(payload)
        # the posted choices are checked against what this server offers, never trusted as they are
        renames = {}  # {model: {source field: field here}}
        for model, d in schema.items():
            for field in d["gone"]:
                choice = request.POST.get(f"field__{model}__{field}", "")
                if choice in d["new"]:
                    renames.setdefault(model, {})[field] = choice
        # new ids per model by source id; fixtures are decided here, data models fill in below
        ids = {}
        for model, d in fixtures.items():
            options = {str(r["id"]): r["id"] for r in d["options"]}
            ids[model] = d["mapped"] | {
                str(row["id"]): options.get(request.POST.get(f"fixture__{model}__{row['id']}", ""))
                for row in d["unmapped"]}
        data = payload["data"]
        data.pop("Organization", None)  # the org exists: its name, email and slug stay as they are
        known = export_schema()
        cols = {name: {f.attname: f for f in export_fields(apps.get_model(APP_LABEL, name))} for name in data}
        problems = []
        order, todo = [], set(data)
        while todo:  # parents first
            ready = sorted(m for m in todo if {t for t in known[m]["fks"].values() if t in data} <= set(order))
            if not ready:
                problems.append(f"Models point at each other: {', '.join(sorted(todo))}")
                break
            order += ready
            todo -= set(ready)
        # required links to fixed values with no match: all of them at once, before anything is written
        bad = {}  # (field, target) -> source ids with no match
        for name, rows in data.items():
            for key, target in payload["schema"][name]["fks"].items():
                field = cols[name].get(renames.get(name, {}).get(key, key))
                if not isinstance(field, ForeignKey) or field.null or target not in fixtures:
                    continue
                for r in rows:
                    if r.get(key) is not None and resolve(ids, target, field, r[key]) is None:
                        bad.setdefault((f"{name}.{field.attname}", target), []).append(r[key])
        problems += [f"{field}: {len(vals)} rows point at {target} {', '.join(map(str, sorted(set(vals))[:3]))}, "
                     "which has no match on this server" for (field, target), vals in bad.items()]
        if problems:
            logger.warning("org backup not importable (%s): %s", who, "; ".join(problems))
            return self.review(request, payload, dropped, problems)
        org_user = self.org_user
        created, lost = Counter(), Counter()  # rows made per model; links with no match, left empty
        # the file's person with the importer's email is the org's admin person: reused, not created again
        admin = Person.objects.filter(owner=the_admin, memberships__user=org_user).first()
        email = (the_admin.email or "").lower()
        admin_src = next((str(r["id"]) for r in data.get("Person", [])
                          if admin and email and (r.get("email") or "").lower() == email), None)
        if admin_src:
            ids["Person"] = {admin_src: admin.pk}

        kept, left = Counter(), set()  # file rows kept as they are here; file rows the user left out

        def skip(name, src):  # the admin person and what it already has
            return str(src["id"]) in ids.get(name, {}) or (name, str(src["id"])) in left or (
                name in self.ADMIN_LINKS and admin_src and str(src.get("person_id")) == admin_src)

        def existing(name, src):
            """pk of a row here holding the same unique values as this file row, or None. Parents must be mapped already."""
            model = apps.get_model(APP_LABEL, name)
            owner, back = self.owner(model), {new: old for old, new in renames.get(name, {}).items()}
            sets = [c.fields for c in model._meta.constraints if isinstance(c, UniqueConstraint) and not c.condition]
            sets += list(model._meta.unique_together) + [(f.name,) for f in model._meta.concrete_fields if f.unique and not f.primary_key]
            for names in sets:
                look = {}
                for f in map(model._meta.get_field, names):
                    value = src.get(back.get(f.attname, f.attname))
                    try:
                        if f.attname in owner:
                            look[f.attname] = owner[f.attname]
                        elif value is not None and f.attname in cols[name]:
                            look[f.attname] = (resolve(ids, payload["schema"][name]["fks"].get(back.get(f.attname, f.attname)), f, value)
                                               if isinstance(f, ForeignKey) else f.to_python(value))
                    except ValidationError:
                        pass  # the value is reported by the validation below
                if len(look) == len(names) and None not in look.values():  # a NULL never clashes
                    return model.objects.filter(**look).values_list("pk", flat=True).first()

        # the user's fixes: "fix__model__field__value" for every row with that value, "row__model__id__field" for one row
        fixes = {tuple(k.split("__", 3)): v for k, v in request.POST.items() if k.startswith(("fix__", "row__")) and v}
        if fixes:
            for name, rows in data.items():
                for src in rows:
                    for key in src:
                        src[key] = fixes.get(("row", name, str(src["id"]), key), fixes.get(("fix", name, key, str(src[key])), src[key]))
        if fixes:
            with open(saved["path"], "w", encoding="utf-8") as f:  # keeps the fixes made so far
                json.dump(payload, f)
        invalid = [c for name in order for c in self.clashes(name, data[name], cols[name], renames.get(name, {}), skip)]
        if invalid:
            logger.warning("org backup has invalid values, nothing created (%s): %d groups", who, len(invalid))
            return self.review(request, payload, dropped, clashes=invalid)
        # file rows that already exist here, per model; ponytail: only parents known now (fixed values, admin person) are matched
        found = {name: [(src, pk) for src in data[name] if not skip(name, src) and (pk := existing(name, src))] for name in order}
        found = {name: rows for name, rows in found.items() if rows}
        if found and not request.POST.get("existing_seen"):
            return self.review(request, payload, dropped, existing=[
                {"model": name, "rows": [(src["id"], row_label(src)) for src, _ in rows]} for name, rows in found.items()])
        for name, rows in found.items():  # keep: this server's row stands in for the file's; skip: the file's row is left out
            for src, pk in rows:
                choice = request.POST.get(f"rowaction__{name}__{src['id']}") or request.POST.get(f"action__{name}")
                if choice == "skip":
                    left.add((name, str(src["id"])))
                else:
                    ids.setdefault(name, {})[str(src["id"])] = pk
                    kept[name] += 1
        try:
            with transaction.atomic():  # all or nothing
                for name in order:
                    model = apps.get_model(APP_LABEL, name)
                    owner = self.owner(model)
                    stamps = [a for a, f in cols[name].items() if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)]
                    made = []
                    ids.setdefault(name, {})
                    for position, src in enumerate(data[name], 1):
                        where = f"{name} row {position} (id {src['id']})"
                        if skip(name, src):
                            continue
                        kwargs = dict(owner)
                        try:
                            for key, value in src.items():
                                attname = renames.get(name, {}).get(key, key)
                                field = cols[name].get(attname)
                                if field is None or attname == "id":  # removed here, or ignored by the user
                                    continue
                                if not isinstance(field, ForeignKey) or value is None:
                                    kwargs[attname] = field.to_python(value)
                                    continue
                                kwargs[attname] = resolve(ids, payload["schema"][name]["fks"].get(key), field, value)
                                if kwargs[attname] is None:
                                    if not field.null:
                                        raise BackupError(where, f"no {field.related_model.__name__} here for {attname} {value}",
                                                          row_label(src))
                                    lost[f"{name}.{attname}"] += 1
                            obj = model.objects.create(**kwargs)  # not bulk_create: post_save signals (Resource -> Share) must run
                        except ValidationError as e:
                            raise BackupError(where, "; ".join(e.messages), row_label(src)) from e
                        except DatabaseError as e:
                            raise BackupError(where, str(e), row_label(src)) from e
                        created[name] += 1
                        ids[name][str(src["id"])] = obj.pk
                        if stamps:  # create() stamped them with now; the file's values go back in below
                            for a in stamps:
                                if kwargs.get(a) is not None:
                                    setattr(obj, a, kwargs[a])
                            made.append(obj)
                    if made:  # bulk_update does not run pre_save, so auto_now(_add) leaves them alone
                        model.objects.bulk_update(made, stamps, batch_size=500)
        except BackupError as e:
            logger.warning("org backup import failed, nothing created (%s): %s", who, e)
            return self.review(request, payload, dropped, [e.message])
        except Exception:
            logger.exception("org backup import crashed, nothing created (%s)", who)
            return self.review(request, payload, dropped, ["Unexpected error, details are in the server log."])
        self.forget(request)
        counts = ", ".join(f"{n} {m}" for m, n in sorted(created.items()))
        now = {m.__name__: len(pks) for m, pks in org_pks(org_user).items()}  # what the org holds after the import
        request.session["org_backup_result"] = [
            {"model": m, "imported": created[m], "kept": kept[m], "now": now.get(m, 0)} for m in sorted(created.keys() | kept.keys())]
        messages.success(request, f"Imported the backup into '{org_user.username}': {sum(created.values())} rows.")
        logger.info("org backup imported (%s org=%s): %s", who, org_user.username, counts)
        warnings = []
        if kept:
            warnings.append("Already on this server, kept as they were: " + ", ".join(f"{m} ({n})" for m, n in sorted(kept.items())) + ".")
        if lost:
            warnings.append("Links with no match on this server were left empty: "
                            + ", ".join(f"{f} ({n})" for f, n in sorted(lost.items())) + ".")
        ignored = [f"{m}.{f}" for m, d in schema.items() for f in d["gone"] if f not in renames.get(m, {})]
        if ignored:
            warnings.append(f"Fields of the backup that were not imported: {', '.join(ignored)}.")
        if dropped:
            warnings.append(f"Parts of the backup that are not on this server were skipped: {', '.join(dropped)}.")
        for text in warnings:
            logger.warning("org backup import (%s): %s", who, text)
            messages.warning(request, text)
        return redirect("syncope:org_import_backup", username=org_user.username)


class ExportView(View):
    """GET: page with the button. POST: the button, returns the json file."""
    template_name = "syncope/export.html"

    def dispatch(self, request, *args, **kwargs):
        self.org_user = get_object_or_404(CustomUser, username=kwargs["username"])
        # moves the whole org's data, so ADMIN only (the middleware also lets MEMBERs in)
        if Role.ADMIN not in AccessControl.org_role_ids(request.user, self.org_user.username):
            return HttpResponseForbidden("Only organization admins can export data.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, username):
        return render(request, self.template_name, {"org_user": self.org_user, "url_username": username})

    def post(self, request, username):
        return HttpResponse(
            json.dumps(export_org(self.org_user), cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="syncope-{username}-{timezone.localdate():%Y-%m-%d}.json"'})

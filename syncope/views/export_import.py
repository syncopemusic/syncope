import json

from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.generic import View

from functools import reduce
from operator import and_, or_

from django.apps import apps
from django.db.models import ForeignKey, Q

from syncope.models import CustomUser, Role
from syncope.permissions import AccessControl

APP_LABEL = "syncope"
SKIP = {"Invitation", "Share", "ShareVisit"}


def _fks(model):
    return [f for f in model._meta.concrete_fields if isinstance(f, ForeignKey)]


def _user_fks(model):
    """Ownership FKs: rows pointing at the org account. Not exported, the importer sets them."""
    return [f for f in _fks(model) if f.related_model is CustomUser]


def _follow(model):
    """FKs that link to other exported rows: not the user, not self (Person.owner would pull in personal profiles)."""
    return [f for f in _fks(model) if f.related_model not in (CustomUser, model)]


def _rows(qs):
    model = qs.model
    skip = {f.attname for f in _user_fks(model)} | {f.attname for f in _fks(model) if f.related_model is model}
    return [
        {f.attname: getattr(obj, f.attname) for f in model._meta.concrete_fields if f.attname not in skip}
        for obj in qs.order_by("pk")
    ]


def export_org(org_user):
    """
    Everything under org_user, read from the models so new fields and models need no change here.
    One flat list per model, FKs as source ids; the importer remaps them.
    """
    # include_auto_created: M2M join tables (Project_guests, ...) come back as ordinary models
    models = [m for m in apps.get_app_config(APP_LABEL).get_models(include_auto_created=True)
              if m is not CustomUser and m.__name__ not in SKIP]
    fixtures = [m for m in models if not _fks(m)]
    # FKs leaving the app (CustomUser_groups -> auth.Group) are not ours
    data = [m for m in models if _fks(m) and all(f.related_model._meta.app_label == APP_LABEL for f in _fks(m))]

    pks = {m: set() for m in data}
    for m in data:  # rows the org owns directly
        if _user_fks(m):
            q = reduce(or_, (Q(**{f.name: org_user}) for f in _user_fks(m)))
            pks[m] = set(m.objects.filter(q).values_list("pk", flat=True))

    size = -1
    while size != sum(map(len, pks.values())):  # until a pass adds nothing
        size = sum(map(len, pks.values()))
        for m in data:
            for f in _follow(m):  # parents of what we have (Membership -> Person)
                if f.related_model in pks:
                    pks[f.related_model] |= set(
                        m.objects.filter(pk__in=pks[m]).exclude(**{f.attname: None}).values_list(f.attname, flat=True))
            if not _user_fks(m):  # children of what we have (Event -> Attendance), all their parents must be ours
                fks = [f for f in _follow(m) if f.related_model in pks]
                if fks:
                    inside = [Q(**{f"{f.attname}__in": pks[f.related_model]}) for f in fks]
                    empty = [Q(**{f"{f.attname}__isnull": True}) for f in fks]
                    q = reduce(or_, inside) & reduce(and_, (i | e for i, e in zip(inside, empty)))
                    pks[m] |= set(m.objects.filter(q).values_list("pk", flat=True))

    return {
        "version": 3,
        "fixtures": {m.__name__: _rows(m.objects.all()) for m in fixtures},
        "data": {m.__name__: _rows(m.objects.filter(pk__in=pks[m])) for m in data},
    }


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
        body = json.dumps(export_org(self.org_user), cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
        response = HttpResponse(body, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="syncope-{username}-{timezone.localdate():%Y-%m-%d}.json"'
        return response



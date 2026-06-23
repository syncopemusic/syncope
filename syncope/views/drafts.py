import uuid
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from syncope.utils import add_query_param


def save_draft(request, key, fields):
    request.session.setdefault("drafts", {})[key] = {
        f: request.POST.get(f, "") for f in fields
    }
    request.session.modified = True


def get_draft(request, key):
    return request.session.get("drafts", {}).get(key, {})


def clear_draft(request, key):
    drafts = request.session.get("drafts", {})
    if key in drafts:
        del drafts[key]
        request.session.modified = True


class DraftMixin:
    def get_draft_key(self):
        key = self.request.GET.get('draft_key')
        if key:
            return key
        pk = self.kwargs.get('pk', 'new')
        return f"{self.__class__.__name__}_{pk}"

    def get_initial(self):
        initial = super().get_initial()
        draft = get_draft(self.request, self.get_draft_key())
        for k, v in draft.items():
            if k not in initial:
                initial[k] = v
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['draft_key'] = self.request.GET.get('draft_key', '')
        return ctx

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not self.request.POST:
            draft = get_draft(self.request, self.get_draft_key())
            if draft:
                form.initial.update(draft)
            # URL select params always win over draft values
            for field in getattr(self, 'person_preset_fields', []):
                pk = self.request.GET.get(f'select_{field}')
                if pk:
                    form.initial[field] = pk
            for query_key, form_key in getattr(self, 'person_preset_map', {}).items():
                pk = self.request.GET.get(query_key)
                if pk:
                    form.initial[form_key] = pk
        return form

    def _get_draft_querydict(self):
        from django.http import QueryDict
        draft = get_draft(self.request, self.get_draft_key())
        if not draft:
            return None
        qd = QueryDict(mutable=True)
        qd.update(draft)
        return qd

    def _get_formset_from_draft(self, formset_class, prefix, data=None, **kwargs):
        if data:
            return formset_class(data, prefix=prefix, **kwargs)
        dq = self._get_draft_querydict()
        if dq and f'{prefix}-TOTAL_FORMS' in dq:
            return formset_class(dq, prefix=prefix, **kwargs)
        return formset_class(prefix=prefix, **kwargs)

    def form_invalid(self, form):
        fields = [k for k in self.request.POST if k not in ('csrfmiddlewaretoken', 'draft_key')]
        save_draft(self.request, self.get_draft_key(), fields)
        return super().form_invalid(form)

    def form_valid(self, form):
        clear_draft(self.request, self.get_draft_key())
        return super().form_valid(form)


@login_required
@require_POST
def save_draft_and_go(request):
    goto = request.GET.get('goto', '')
    next_url = request.GET.get('next', '')
    host = request.get_host()
    require_https = request.is_secure()

    if not goto or not url_has_allowed_host_and_scheme(goto, allowed_hosts={host}, require_https=require_https):
        return HttpResponseBadRequest()

    draft_key = request.POST.get('draft_key') or str(uuid.uuid4())
    fields = [k for k in request.POST if k not in ('csrfmiddlewaretoken', 'draft_key')]
    save_draft(request, draft_key, fields)

    safe_next = next_url if url_has_allowed_host_and_scheme(next_url, allowed_hosts={host}, require_https=require_https) else '/'
    return_url = add_query_param(safe_next, {'draft_key': draft_key})
    return redirect(add_query_param(goto, {'next': return_url}))

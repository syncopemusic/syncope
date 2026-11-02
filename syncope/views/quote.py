from itertools import zip_longest

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.views.generic import View

from syncope.models import CustomUser, Person, Quote
from syncope.views.resource import KIND_CONFIG


@method_decorator(login_required, name='dispatch')
class QuotesEditView(View):
    """Add/remove quotes for a Song or Person (same shape as ResourcesEditView).

    The page's own song/person comes from the URL and the owner from the URL username;
    the Song page also takes an optional person per quote.
    """
    template_name = 'syncope/quotes_edit.html'
    kind = None

    def _setup(self, request, username, pk):
        cfg = KIND_CONFIG[self.kind]
        self.fk_name = cfg['fk_name']
        self.owner_user = get_object_or_404(CustomUser, username=username)
        self.owner = cfg['get_owner'](self.owner_user, pk)
        self.detail_url = reverse(f'syncope:{cfg["detail_url"]}', kwargs={'username': username, 'pk': pk})
        return cfg['can_edit'](request.user, self.owner_user, self.owner)

    def get(self, request, username, pk):
        if not self._setup(request, username, pk):
            return HttpResponseForbidden("You don't have permission to edit these quotes.")
        return render(request, self.template_name, {
            'owner': self.owner,
            'kind': self.kind,
            'quotes': self.owner.quotes.select_related('person', 'song'),
            'url_username': username,
            'owner_detail_url': self.detail_url,
        })

    def post(self, request, username, pk):
        if not self._setup(request, username, pk):
            return HttpResponseForbidden("You don't have permission to edit these quotes.")
        remove_ids = [int(k[7:]) for k in request.POST if k.startswith('remove_') and k[7:].isdigit()]
        persons = Person.objects.in_org_user(self.owner_user)
        rows = zip_longest(*(request.POST.getlist(f'new_{f}') for f in ('word', 'bar_number', 'date', 'person')), fillvalue='')

        with transaction.atomic():
            self.owner.quotes.filter(pk__in=remove_ids).delete()
            for word, bar_number, date, person_id in rows:
                if not word.strip():
                    continue
                quote = Quote(
                    owner=self.owner_user, word=word.strip(), bar_number=bar_number.strip() or None,
                    date=parse_date(date), **{self.fk_name: self.owner},
                )
                if self.kind == 'song' and person_id.isdigit():
                    quote.person = persons.filter(pk=person_id).first()
                quote.save()

        messages.success(request, "Quotes updated successfully!")
        return redirect(request.get_full_path())

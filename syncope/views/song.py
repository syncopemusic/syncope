from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView,  DetailView, View
from django.views.generic.edit import DeleteView
from django.db.models import  Q
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from syncope.models import Song
from syncope.models import Event, SongResource, Resource
from syncope.forms import  SongForm
from syncope.forms import  QuoteFormSet, LyricsTranslationFormSet, SongResourceFormSet
from syncope.mixins import  SongOwnerMixin
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list



@method_decorator(login_required, name='dispatch')
class SongListView(SongOwnerMixin, ListView):
    model = Song
    template_name = "syncope/song_dashboard.html"
    context_object_name = "songs"
    permission_check_method = AccessControl.can_view_song_list

    def get_queryset(self):
        qs = AccessControl.can_view_song_list(self.request.user, self.owner_user)
        q = self.request.GET.get('q', '').strip()
        if q:
            if q.isdigit():
                qs = qs.filter(internal_id=int(q))
            else:
                qs = qs.filter(
                    Q(title__icontains=q) |
                    Q(composer__last_name__icontains=q) |
                    Q(keywords__icontains=q)
                ).distinct()

        # Handle sorting
        sort = self.request.GET.get('sort', 'id')
        reverse = self.request.GET.get('reverse', 'false') == 'true'

        sort_field_map = {
            'id': 'internal_id',
            'title': 'title',
            'composer': 'composer__last_name',
        }

        sort_field = sort_field_map.get(sort, 'internal_id')
        if reverse:
            sort_field = f'-{sort_field}'

        return qs.order_by(sort_field).prefetch_related('song_resource__resource')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["url_username"] = self.owner_user.username
        context["q"] = self.request.GET.get('q', '')
        context["current_sort"] = self.request.GET.get('sort', 'id')
        context["reverse"] = self.request.GET.get('reverse', 'false') == 'true'
        for song in context['songs']:
            song.resource_icons = resource_icon_list(song.song_resource.all())
        return context


@method_decorator(login_required, name='dispatch')
class SongDetailView(SongOwnerMixin, DetailView):
    model = Song
    template_name = "syncope/song_page.html"
    context_object_name = "song"
    permission_check_method = AccessControl.can_view_song

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username

        song = self.get_object()
        events = Event.objects.filter(
            eventsong__song=song
        ).order_by('-started_at').distinct()
        context['events'] = events
        context['song_resources'] = resource_icon_list(
            song.song_resource.select_related('resource').order_by('order')
        )

        return context


@method_decorator(login_required, name='dispatch')
class SongCreateView(SongOwnerMixin, CreateView):
    form_class = SongForm
    template_name = "syncope/song_form2.html"
    permission_check_method = AccessControl.can_manage_song

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.owner_user
        return kwargs

    def get_context_data(self, quote_formset=None, translation_formset=None, songresource_formset=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        if quote_formset is not None:
            context['quote_formset'] = quote_formset
        elif self.request.POST:
            context['quote_formset'] = QuoteFormSet(self.request.POST, prefix='quotes')
        else:
            context['quote_formset'] = QuoteFormSet(prefix='quotes')
        if translation_formset is not None:
            context['translation_formset'] = translation_formset
        elif self.request.POST:
            context['translation_formset'] = LyricsTranslationFormSet(
                self.request.POST, prefix='translations', user=self.owner_user
            )
        else:
            context['translation_formset'] = LyricsTranslationFormSet(
                prefix='translations', user=self.owner_user
            )
        if songresource_formset is not None:
            context['songresource_formset'] = songresource_formset
        elif self.request.POST:
            context['songresource_formset'] = SongResourceFormSet(
                self.request.POST, prefix='resources', user=self.owner_user
            )
        else:
            context['songresource_formset'] = SongResourceFormSet(
                prefix='resources', user=self.owner_user
            )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') == 'add_kw_row':
            self.object = None
            form = self.get_form()
            post_data = request.POST.copy()
            total = int(post_data.get('quotes-TOTAL_FORMS', 0))
            post_data['quotes-TOTAL_FORMS'] = total + 1
            kf = QuoteFormSet(post_data, prefix='quotes')
            return self.render_to_response(self.get_context_data(form=form, quote_formset=kf))
        if request.POST.get('action') == 'add_translation_row':
            self.object = None
            form = self.get_form()
            post_data = request.POST.copy()
            total = int(post_data.get('translations-TOTAL_FORMS', 0))
            post_data['translations-TOTAL_FORMS'] = total + 1
            tf = LyricsTranslationFormSet(post_data, prefix='translations', user=self.owner_user)
            return self.render_to_response(self.get_context_data(form=form, translation_formset=tf))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.user = self.owner_user
        self.object = form.save()
        kf = QuoteFormSet(self.request.POST, instance=self.object, prefix='quotes')
        if kf.is_valid():
            kf.save()
        tf = LyricsTranslationFormSet(
            self.request.POST, instance=self.object, prefix='translations', user=self.owner_user
        )
        if tf.is_valid():
            tf.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return next_url
        return reverse_lazy("syncope:song_page", kwargs={
            "username": self.owner_user.username,
            "pk": self.object.pk
        })


@method_decorator(login_required, name='dispatch')
class SongUpdateView(SongOwnerMixin, UpdateView):
    form_class = SongForm
    template_name = "syncope/song_form2.html"
    permission_check_method = AccessControl.can_manage_song

    def get_queryset(self):
        return Song.objects.filter(user=self.owner_user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.owner_user
        return kwargs

    def get_context_data(self, quote_formset=None, translation_formset=None, resource_formset=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        if quote_formset is not None:
            context['quote_formset'] = quote_formset
        elif self.request.POST:
            context['quote_formset'] = QuoteFormSet(self.request.POST, instance=self.object, prefix='quotes')
        else:
            context['quote_formset'] = QuoteFormSet(instance=self.object, prefix='quotes')
        if translation_formset is not None:
            context['translation_formset'] = translation_formset
        elif self.request.POST:
            context['translation_formset'] = LyricsTranslationFormSet(
                self.request.POST, instance=self.object, prefix='translations', user=self.owner_user
            )
        else:
            context['translation_formset'] = LyricsTranslationFormSet(
                instance=self.object, prefix='translations', user=self.owner_user
            )
        if resource_formset is not None:
            context['resource_formset'] = resource_formset
        elif self.request.POST:
            context['resource_formset'] = SongResourceFormSet(
                self.request.POST, instance=self.object, prefix='resources', user=self.owner_user
            )
        else:
            context['resource_formset'] = SongResourceFormSet(
                instance=self.object, prefix='resources', user=self.owner_user
            )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') == 'add_kw_row':
            self.object = self.get_object()
            form = self.get_form()
            post_data = request.POST.copy()
            total = int(post_data.get('quotes-TOTAL_FORMS', 0))
            post_data['quotes-TOTAL_FORMS'] = total + 1
            kf = QuoteFormSet(post_data, instance=self.object, prefix='quotes')
            return self.render_to_response(self.get_context_data(form=form, quote_formset=kf))
        if request.POST.get('action') == 'add_translation_row':
            self.object = self.get_object()
            form = self.get_form()
            post_data = request.POST.copy()
            total = int(post_data.get('translations-TOTAL_FORMS', 0))
            post_data['translations-TOTAL_FORMS'] = total + 1
            tf = LyricsTranslationFormSet(post_data, instance=self.object, prefix='translations', user=self.owner_user)
            return self.render_to_response(self.get_context_data(form=form, translation_formset=tf))
        return super().post(request, *args, **kwargs)

    def _save_resources(self, song, resource_formset):
        song.song_resource.all().delete()
        valid_forms = [
            f for f in resource_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
        ]
        for idx, f in enumerate(valid_forms):
            url = f.cleaned_data['url']
            description = f.cleaned_data.get('description', '')
            resource, created = Resource.objects.get_or_create(
                url=url,
                defaults={'owner': self.owner_user, 'description': description}
            )
            if not created:
                resource.description = description
                resource.save(update_fields=['description'])
            SongResource.objects.create(song=song, resource=resource, order=idx + 1)

    def form_valid(self, form):
        form.instance.user = self.owner_user
        self.object = form.save()
        kf = QuoteFormSet(self.request.POST, instance=self.object, prefix='quotes')
        if kf.is_valid():
            kf.save()
        tf = LyricsTranslationFormSet(
            self.request.POST, instance=self.object, prefix='translations', user=self.owner_user
        )
        if tf.is_valid():
            tf.save()
        rf = SongResourceFormSet(
            self.request.POST, instance=self.object, prefix='resources', user=self.owner_user
        )
        if rf.is_valid():
            self._save_resources(self.object, rf)
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy("syncope:song_page", kwargs={
            "username": self.owner_user.username,
            "pk": self.object.pk
        })


@method_decorator(login_required, name='dispatch')
class SongDeleteView(SongOwnerMixin, DeleteView):
    model = Song
    template_name = "syncope/song_confirm_delete.html"
    permission_check_method = AccessControl.can_manage_song

    def get_success_url(self):
        return reverse_lazy("syncope:song_dashboard", kwargs={
            "username": self.owner_user.username
        })



@method_decorator(login_required, name='dispatch')
class SongQuoteView(SongOwnerMixin, View):
    """Manage quotes for a specific song. Supports ?next= redirect after save."""
    template_name = 'syncope/song_quotes.html'
    permission_check_method = AccessControl.can_manage_song

    def _get_song(self, pk):
        song = get_object_or_404(Song, pk=pk, user=self.owner_user)
        if not AccessControl.can_manage_song(self.request.user, song):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return song

    def _next_url(self, request, username, pk):
        next_url = request.GET.get('next') or request.POST.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return next_url
        return reverse('syncope:song_page', kwargs={'username': username, 'pk': pk})

    def get(self, request, username, pk):
        song = self._get_song(pk)
        formset = QuoteFormSet(instance=song, prefix='quotes')
        return render(request, self.template_name, {
            'song': song,
            'formset': formset,
            'url_username': username,
            'next': request.GET.get('next', ''),
        })

    def post(self, request, username, pk):
        song = self._get_song(pk)
        if request.POST.get('action') == 'add_kw_row':
            post_data = request.POST.copy()
            total = int(post_data.get('quotes-TOTAL_FORMS', 0))
            post_data['quotes-TOTAL_FORMS'] = total + 1
            formset = QuoteFormSet(post_data, instance=song, prefix='quotes')
            return render(request, self.template_name, {
                'song': song,
                'formset': formset,
                'url_username': username,
                'next': request.POST.get('next', ''),
            })
        formset = QuoteFormSet(request.POST, instance=song, prefix='quotes')
        if formset.is_valid():
            formset.save()
            return redirect(self._next_url(request, username, pk))
        return render(request, self.template_name, {
            'song': song,
            'formset': formset,
            'url_username': username,
            'next': request.POST.get('next', ''),
        })



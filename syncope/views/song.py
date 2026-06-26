from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.views.generic import ListView, CreateView, UpdateView,  DetailView, View
from django.views.generic.edit import DeleteView
from django.db.models import Q, Exists, OuterRef, Count, Max
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from syncope.models import Song, EventType
from syncope.models import Event, SongResource, Resource, EventSongResource, EventSong, Project
from syncope.forms import  SongForm
from syncope.forms import  QuoteFormSet, LyricsTranslationFormSet, SongResourceFormSet
from syncope.mixins import  SongOwnerMixin
from syncope.views.drafts import DraftMixin, clear_draft
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list, add_query_param


def save_song_resources(song, resource_formset, owner_user):
    """Save resources from a formset to a song."""
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
            defaults={'owner': owner_user, 'description': description}
        )
        if not created:
            resource.description = description
            resource.save(update_fields=['description'])
        SongResource.objects.create(song=song, resource=resource, order=idx + 1)


@method_decorator(login_required, name='dispatch')
class SongListView(SongOwnerMixin, ListView):
    model = Song
    template_name = "syncope/song_list.html"
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
                    Q(poet__last_name__icontains=q) |
                    Q(arranger__last_name__icontains=q) |
                    Q(origin__icontains=q) |
                    Q(keywords__icontains=q) |
                    Q(languagecode__language_code__icontains=q)
                ).distinct()

        # Handle sorting
        sort = self.request.GET.get('sort', 'id')
        reverse = self.request.GET.get('reverse', 'false') == 'true'

        sort_field_map = {
            'id': 'internal_id',
            'title': 'title',
            'composer': 'composer__last_name',
            'poet': 'poet__last_name',
            'arranger': 'arranger__last_name',
            'origin': 'origin',
            'languagecode': 'languagecode__language_code',
        }

        sort_field = sort_field_map.get(sort, 'internal_id')
        if reverse:
            sort_field = f'-{sort_field}'

        # Annotate with counts for both direct and event-based resources
        qs = qs.annotate(
            has_direct_resources=Count('song_resource', distinct=True),
            has_event_resources=Count('eventsong__event_song_resource', distinct=True),
            concert_count=Count(
                'eventsong__event',
                filter=Q(
                    eventsong__event__event_type_id=EventType.CONCERT,
                    eventsong__event__user=self.owner_user,
                ),
                distinct=True,
            ),
            performance_count=Count(
                'eventsong__event',
                filter=Q(
                    eventsong__event__event_type_id=EventType.PERFORMANCE,
                    eventsong__event__user=self.owner_user,
                ),
                distinct=True,
            ),
        )
        return qs.order_by(sort_field).select_related('composer', 'poet', 'arranger', 'languagecode').prefetch_related('song_resource__resource')


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
    template_name = "syncope/song_detail.html"
    context_object_name = "song"
    permission_check_method = AccessControl.can_view_song

    def get_queryset(self):
        return Song.objects.filter(user=self.owner_user).select_related('languagecode')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username

        song = self.get_object()
        events = Event.objects.filter(
            eventsong__song=song
        ).order_by('-started_at').distinct()

        for event in events:
            event_songs = event.eventsong_set.filter(song=song)
            event_song_resources = EventSongResource.objects.filter(
                event_song__in=event_songs
            ).select_related('resource').order_by('order')
            event.song_resources_in_event = resource_icon_list(event_song_resources)

        context['events'] = events
        context['song_resources'] = resource_icon_list(
            song.song_resource.select_related('resource').order_by('order')
        )
        context['can_manage'] = AccessControl.can_manage_song(self.request.user, song)

        # Build combined resource list: song resources first, then event-song resources
        all_song_resources = [
            {'url': r['url'], 'icon': r['icon'], 'desc': r['desc'], 'event': None, 'share_url': r.get('share_url')}
            for r in context['song_resources']
        ]
        for event in events:
            for r in event.song_resources_in_event:
                all_song_resources.append({
                    'url': r['url'], 'icon': r['icon'], 'desc': r['desc'], 'event': event, 'share_url': r.get('share_url')
                })
        context['all_song_resources'] = all_song_resources

        return context


class SelectPersonInitialMixin:
    person_preset_fields = []
    person_preset_map = {}

    def get_initial(self):
        initial = super().get_initial()
        if self.person_preset_map:
            for query_key, form_key in self.person_preset_map.items():
                pk = self.request.GET.get(query_key)
                if pk:
                    initial[form_key] = pk
        else:
            for field in self.person_preset_fields:
                pk = self.request.GET.get(f'select_{field}')
                if pk:
                    initial[field] = pk
        return initial


@method_decorator(login_required, name='dispatch')
class SongCreateView(DraftMixin, SongOwnerMixin, SelectPersonInitialMixin, CreateView):
    form_class = SongForm
    template_name = "syncope/song_form.html"
    permission_check_method = AccessControl.can_manage_song
    person_preset_fields = ['composer', 'arranger', 'poet', 'translator']

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.owner_user
        return kwargs

    def get_context_data(self, quote_formset=None, translation_formset=None, songresource_formset=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        context['can_manage'] = True
        post_data = self.request.POST or None

        context['quote_formset'] = (
            quote_formset or self._get_formset_from_draft(
                QuoteFormSet, 'quotes',
                data=post_data
            )
        )
        context['translation_formset'] = (
            translation_formset or self._get_formset_from_draft(
                LyricsTranslationFormSet, 'translations',
                data=post_data,
                user=self.owner_user
            )
        )
        context['songresource_formset'] = (
            songresource_formset or self._get_formset_from_draft(
                SongResourceFormSet, 'resources',
                data=post_data,
                user=self.owner_user
            )
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
        clear_draft(self.request, self.get_draft_key())
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
            save_song_resources(self.object, rf, self.owner_user)
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next', '')
        host = self.request.get_host()
        safe_next = next_url if (next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={host})) else None
        draft_key = self.request.GET.get('draft_key')

        auto_add_event = self.request.GET.get('auto_add_event')
        auto_add_project = self.request.GET.get('auto_add_project')

        if safe_next and auto_add_event:
            event = Event.objects.filter(pk=auto_add_event, user=self.owner_user).first()
            if event:
                next_order = (event.eventsong_set.aggregate(Max('order'))['order__max'] or 0) + 1
                EventSong.objects.get_or_create(
                    event=event, song=self.object,
                    defaults={'order': next_order, 'encore': False},
                )
            if draft_key:
                safe_next = add_query_param(safe_next, {'draft_key': draft_key})
            return safe_next

        if safe_next and auto_add_project:
            project = Project.objects.filter(pk=auto_add_project, user=self.owner_user).first()
            if project:
                project.songs.add(self.object)
            if draft_key:
                safe_next = add_query_param(safe_next, {'draft_key': draft_key})
            return safe_next

        if safe_next:
            return add_query_param(safe_next, {'select_song': self.object.pk})
        return reverse_lazy("syncope:song_detail", kwargs={
            "username": self.owner_user.username, "pk": self.object.pk
        })


@method_decorator(login_required, name='dispatch')
class SongUpdateView(DraftMixin, SongOwnerMixin, SelectPersonInitialMixin, UpdateView):
    form_class = SongForm
    template_name = "syncope/song_form.html"
    permission_check_method = AccessControl.can_manage_song
    person_preset_fields = ['composer', 'arranger', 'poet', 'translator']

    def get_queryset(self):
        return Song.objects.filter(user=self.owner_user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.owner_user
        return kwargs

    def get_context_data(self, quote_formset=None, translation_formset=None, resource_formset=None, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        context['can_manage'] = True
        post_data = self.request.POST or None

        context['quote_formset'] = (
            quote_formset or self._get_formset_from_draft(
                QuoteFormSet, 'quotes',
                data=post_data,
                instance=self.object
            )
        )
        context['translation_formset'] = (
            translation_formset or self._get_formset_from_draft(
                LyricsTranslationFormSet, 'translations',
                data=post_data,
                instance=self.object,
                user=self.owner_user
            )
        )
        context['resource_formset'] = (
            resource_formset or self._get_formset_from_draft(
                SongResourceFormSet, 'resources',
                data=post_data,
                instance=self.object,
                user=self.owner_user
            )
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
        save_song_resources(song, resource_formset, self.owner_user)

    def form_valid(self, form):
        clear_draft(self.request, self.get_draft_key())
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
        return reverse_lazy("syncope:song_detail", kwargs={
            "username": self.owner_user.username,
            "pk": self.object.pk
        })


@method_decorator(login_required, name='dispatch')
class SongDeleteView(SongOwnerMixin, DeleteView):
    model = Song
    template_name = "syncope/song_confirm_delete.html"
    permission_check_method = AccessControl.can_manage_song

    def dispatch(self, request, *args, **kwargs):
        song = self.get_object()
        if not AccessControl.can_manage_song(request.user, song):
            return HttpResponseForbidden("Only admins can delete songs.")
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        song = self.get_object()
        song_title = song.title
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f"Successfully deleted song '{song_title}'.")
        return response

    def get_success_url(self):
        return reverse_lazy("syncope:song_list", kwargs={
            "username": self.owner_user.username
        })

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        context['can_manage'] = True
        return context



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
        return reverse('syncope:song_detail', kwargs={'username': username, 'pk': pk})

    def get(self, request, username, pk):
        song = self._get_song(pk)
        formset = QuoteFormSet(instance=song, prefix='quotes')
        return render(request, self.template_name, {
            'song': song,
            'formset': formset,
            'url_username': username,
            'next': request.GET.get('next', ''),
            'can_manage': True,
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



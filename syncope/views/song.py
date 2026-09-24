from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, HttpResponseForbidden, HttpResponseBadRequest
from django.views.generic import ListView, CreateView, UpdateView,  DetailView, View
from django.views.generic.edit import DeleteView
from django.db.models import Q, Exists, OuterRef, Count, Max
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from syncope.models import Song, EventType, CustomUser, Person
from syncope.models import Event, EventSong, Project
from syncope.forms import SongMetaForm, SongLyricsForm, SONG_PERSON_FIELD_SKILLS
from syncope.forms import QuoteFormSet, LyricsTranslationFormSet
from syncope.mixins import  SongOwnerMixin
from syncope.views.drafts import DraftMixin, clear_draft
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list, add_query_param, safe_next_url
from syncope.breadcrumbs import event_breadcrumbs, with_origin, DEFAULT_EVENT_ORIGIN
from syncope.views.resource import song_related_resource_rows


def _build_song_queryset(qs, q):
    """Apply the search filter shared by the song list page and its AJAX search."""
    q = q.strip()
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
    return qs


def _annotate_song_queryset(qs, owner_user):
    """Add resource/performance-count annotations shared by the song list page and its AJAX search."""
    return qs.annotate(
        has_direct_resources=Count('song_resource', distinct=True),
        has_event_resources=Count('eventsong__event_song_resource', distinct=True),
        concert_count=Count(
            'eventsong__event',
            filter=Q(
                eventsong__event__event_type_id=EventType.CONCERT,
                eventsong__event__user=owner_user,
            ),
            distinct=True,
        ),
        performance_count=Count(
            'eventsong__event',
            filter=Q(
                eventsong__event__event_type_id=EventType.PERFORMANCE,
                eventsong__event__user=owner_user,
            ),
            distinct=True,
        ),
    )


def _apply_song_sort(qs, request):
    """Apply column sorting shared by the song list page and its AJAX search."""
    sort = request.GET.get('sort', 'id')
    reverse = request.GET.get('reverse', 'false') == 'true'

    sort_field_map = {
        'id': 'internal_id',
        'title': 'title',
        'composer': 'composer__last_name',
        'poet': 'poet__last_name',
        'arranger': 'arranger__last_name',
        # Origin/Lang columns are hidden from the table for now but kept sortable.
        'origin': 'origin',
        'languagecode': 'languagecode__language_code',
    }

    sort_field = sort_field_map.get(sort, 'internal_id')
    if reverse:
        sort_field = f'-{sort_field}'
    return qs.order_by(sort_field)


@method_decorator(login_required, name='dispatch')
class SongListView(SongOwnerMixin, ListView):
    model = Song
    template_name = "syncope/song_list.html"
    context_object_name = "songs"
    permission_check_method = AccessControl.can_view_song_list

    def get_queryset(self):
        qs = AccessControl.can_view_song_list(self.request.user, self.owner_user)
        qs = _build_song_queryset(qs, self.request.GET.get('q', ''))
        qs = _annotate_song_queryset(qs, self.owner_user)
        qs = _apply_song_sort(qs, self.request)
        return qs.select_related('composer', 'poet', 'arranger').prefetch_related('song_resource__resource')


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["url_username"] = self.owner_user.username
        context["q"] = self.request.GET.get('q', '')
        context["current_sort"] = self.request.GET.get('sort', 'id')
        context["reverse"] = self.request.GET.get('reverse', 'false') == 'true'
        for song in context['songs']:
            song.resource_icons = resource_icon_list(song.song_resource.all())
        return context


@login_required
def song_list_search(request, username):
    owner_user = get_object_or_404(CustomUser, username=username)
    qs = AccessControl.can_view_song_list(request.user, owner_user)
    q = request.GET.get('q', '')
    qs = _build_song_queryset(qs, q)
    qs = _annotate_song_queryset(qs, owner_user)
    qs = _apply_song_sort(qs, request)
    songs = qs.select_related('composer', 'poet', 'arranger').prefetch_related('song_resource__resource')
    for song in songs:
        song.resource_icons = resource_icon_list(song.song_resource.all())
    return render(request, 'syncope/song_list_results.html', {
        'songs': songs,
        'url_username': username,
        'q': q,
        'current_sort': request.GET.get('sort', 'id'),
        'reverse': request.GET.get('reverse', 'false') == 'true',
    })


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

        from_event_pk = self.request.GET.get('from_event')
        from_event = Event.objects.filter(pk=from_event_pk, user=self.owner_user).first() if from_event_pk else None
        if from_event:
            breadcrumbs, _ = event_breadcrumbs(
                self.request, self.owner_user.username, from_event, current_label=song.title
            )
            context['breadcrumbs'] = breadcrumbs
            context['return_url'] = breadcrumbs[-2]['url']
            context['return_label'] = f"Return to {breadcrumbs[-2]['label']}"
        else:
            context['breadcrumbs'] = [
                {'label': 'Songs', 'url': reverse('syncope:song_list', kwargs={'username': self.owner_user.username})},
                {'label': song.title, 'url': None},
            ]
        events = Event.objects.filter(
            eventsong__song=song
        ).order_by('-started_at').distinct()

        context['events'] = events
        context['can_manage'] = AccessControl.can_manage_song(self.request.user, song)

        context['song_resources'] = resource_icon_list(
            song.song_resource.select_related('resource').order_by('order')
        )
        context['related_song_resources'] = song_related_resource_rows(song)

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
    form_class = SongMetaForm
    template_name = "syncope/song_meta_edit.html"
    permission_check_method = AccessControl.can_manage_song
    person_preset_fields = ['composer', 'arranger', 'poet', 'translator']

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.owner_user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        context['can_manage'] = True
        context['cancel_url'] = safe_next_url(
            self.request, reverse('syncope:song_list', kwargs={'username': self.owner_user.username})
        )
        return context

    def form_valid(self, form):
        clear_draft(self.request, self.get_draft_key())
        form.instance.user = self.owner_user
        if form.instance.internal_id is None:
            max_id = Song.objects.filter(user=self.owner_user).aggregate(Max("internal_id"))["internal_id__max"]
            form.instance.internal_id = (max_id or 0) + 1
        self.object = form.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next', '')
        host = self.request.get_host()
        safe_next = next_url if (next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={host})) else None
        draft_key = self.request.POST.get('draft_key') or self.request.GET.get('draft_key')

        auto_add_event = self.request.POST.get('auto_add_event') or self.request.GET.get('auto_add_event')
        auto_add_project = self.request.POST.get('auto_add_project') or self.request.GET.get('auto_add_project')

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
class SongMetaEditView(DraftMixin, SongOwnerMixin, SelectPersonInitialMixin, UpdateView):
    """Details subpage: identifying fields, composer/arranger/poet/translator pickers, and Delete."""
    form_class = SongMetaForm
    template_name = "syncope/song_meta_edit.html"
    permission_check_method = AccessControl.can_manage_song
    person_preset_fields = ['composer', 'arranger', 'poet', 'translator']

    def get_queryset(self):
        return Song.objects.filter(user=self.owner_user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.owner_user
        return kwargs

    def _from_event_and_origin(self):
        from_event_pk = self.request.GET.get('from_event') or self.request.POST.get('from_event')
        origin_key = self.request.GET.get('origin') or self.request.POST.get('origin') or DEFAULT_EVENT_ORIGIN
        return from_event_pk, origin_key

    def _song_detail_url(self):
        from_event_pk, origin_key = self._from_event_and_origin()
        url = reverse('syncope:song_detail', kwargs={'username': self.owner_user.username, 'pk': self.object.pk})
        if from_event_pk:
            url = with_origin(add_query_param(url, {'from_event': from_event_pk}), origin_key)
        return url

    def _return_target(self):
        from_event_pk, origin_key = self._from_event_and_origin()
        if from_event_pk:
            event = Event.objects.filter(pk=from_event_pk, user=self.owner_user).first()
            if event:
                event_url = reverse('syncope:event_detail', kwargs={'username': self.owner_user.username, 'pk': event.pk})
                return with_origin(event_url, origin_key), f"Return to {event}"
        return None, None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        context['can_manage'] = True
        context['cancel_url'] = self._song_detail_url()
        context['return_url'], context['return_label'] = self._return_target()
        return context

    def form_valid(self, form):
        clear_draft(self.request, self.get_draft_key())
        form.instance.user = self.owner_user
        self.object = form.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return self._song_detail_url()


@login_required
def song_person_search(request, username, field):
    """AJAX single-person search for the Meta subpage's composer/arranger/poet/translator picker."""
    owner_user = get_object_or_404(CustomUser, username=username)
    skill_id = SONG_PERSON_FIELD_SKILLS.get(field)
    if skill_id is None:
        return HttpResponseBadRequest()
    q = request.GET.get('q', '')
    persons = Person.objects.for_user_with_skill(user=owner_user, skill_id=skill_id).matching_name(q)
    return render(request, 'syncope/song_person_search_results.html', {
        'persons': persons[:25],
        'search_q': q,
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

    def _from_event_and_origin(self):
        from_event_pk = self.request.GET.get('from_event') or self.request.POST.get('from_event')
        origin_key = self.request.GET.get('origin') or self.request.POST.get('origin') or DEFAULT_EVENT_ORIGIN
        return from_event_pk, origin_key

    def delete(self, request, *args, **kwargs):
        song = self.get_object()
        song_title = song.title
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f"Successfully deleted song '{song_title}'.")
        return response

    def get_success_url(self):
        from_event_pk, origin_key = self._from_event_and_origin()
        if from_event_pk:
            event = Event.objects.filter(pk=from_event_pk, user=self.owner_user).first()
            if event:
                event_url = reverse("syncope:event_detail", kwargs={
                    "username": self.owner_user.username, "pk": event.pk
                })
                return with_origin(event_url, origin_key)
        return reverse("syncope:song_list", kwargs={
            "username": self.owner_user.username
        })

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.owner_user.username
        context['can_manage'] = True
        from_event_pk, origin_key = self._from_event_and_origin()
        cancel_url = reverse('syncope:song_detail', kwargs={'username': self.owner_user.username, 'pk': self.object.pk})
        if from_event_pk:
            cancel_url = with_origin(add_query_param(cancel_url, {'from_event': from_event_pk}), origin_key)
        context['cancel_url'] = cancel_url
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
        formset = QuoteFormSet(instance=song, prefix='quotes', user=song.user)
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
            formset = QuoteFormSet(post_data, instance=song, prefix='quotes', user=song.user)
            return render(request, self.template_name, {
                'song': song,
                'formset': formset,
                'url_username': username,
                'next': request.POST.get('next', ''),
            })
        formset = QuoteFormSet(request.POST, instance=song, prefix='quotes', user=song.user)
        if formset.is_valid():
            formset.save()
            return redirect(self._next_url(request, username, pk))
        return render(request, self.template_name, {
            'song': song,
            'formset': formset,
            'url_username': username,
            'next': request.POST.get('next', ''),
        })


@method_decorator(login_required, name='dispatch')
class SongLyricsEditView(SongOwnerMixin, View):
    """Manage lyrics, language, and translations for a specific song."""
    template_name = 'syncope/song_lyrics_edit.html'
    permission_check_method = AccessControl.can_manage_song

    def _get_song(self, pk):
        song = get_object_or_404(Song, pk=pk, user=self.owner_user)
        if not AccessControl.can_manage_song(self.request.user, song):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return song

    def _context(self, song, username, form=None, translation_formset=None):
        return {
            'song': song,
            'form': form or SongLyricsForm(instance=song, user=self.owner_user),
            'translation_formset': translation_formset or LyricsTranslationFormSet(
                instance=song, prefix='translations', user=self.owner_user
            ),
            'url_username': username,
            'can_manage': True,
        }

    def get(self, request, username, pk):
        song = self._get_song(pk)
        return render(request, self.template_name, self._context(song, username))

    def post(self, request, username, pk):
        song = self._get_song(pk)
        form = SongLyricsForm(request.POST, instance=song, user=self.owner_user)
        tf = LyricsTranslationFormSet(request.POST, instance=song, prefix='translations', user=self.owner_user)
        if form.is_valid() and tf.is_valid():
            form.save()
            tf.save()
            return redirect('syncope:song_detail', username=username, pk=song.pk)
        return render(request, self.template_name, self._context(song, username, form=form, translation_formset=tf))



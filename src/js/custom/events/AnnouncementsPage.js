/*
 * AnnouncementsPage — full-page feed for announcements and events.
 *
 * First source: Chicago Public Library Events from City of Chicago Socrata.
 */
(function () {
    var _instance = null;

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _dateValue(d) {
        if (!d) { return ''; }
        return d.toISOString().slice(0, 10);
    }

    function _fmtDateTime(value) {
        if (!value) { return 'Time TBD'; }
        var d = new Date(value);
        if (isNaN(d.getTime())) { return value; }
        return d.toLocaleString([], {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit'
        });
    }

    function _fmtDate(value) {
        if (!value) { return ''; }
        var d = new Date(value);
        if (isNaN(d.getTime())) { return value; }
        return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function _fmtTime(value) {
        if (!value) { return ''; }
        var d = new Date(value);
        if (isNaN(d.getTime())) { return value; }
        return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }

    function _fmtRange(event) {
        if (!event || !event.start) { return 'Time TBD'; }
        var start = _fmtDateTime(event.start);
        if (!event.end) { return start; }
        var s = new Date(event.start);
        var e = new Date(event.end);
        if (isNaN(s.getTime()) || isNaN(e.getTime())) {
            return start + ' - ' + event.end;
        }
        if (s.toDateString() === e.toDateString()) {
            return _fmtDate(event.start) + ' · ' + _fmtTime(event.start) + ' - ' + _fmtTime(event.end);
        }
        return start + ' - ' + _fmtDateTime(event.end);
    }

    function _chip(label) {
        if (!label) { return ''; }
        return '<span class="oae-chip"><i class="fa fa-circle-o"></i>' + _esc(label) + '</span>';
    }

    function _detailChip(kind, label) {
        if (!label) { return ''; }
        return '<span class="oae-affect-chip"><em>' + _esc(kind) + '</em>' + _esc(label) + '</span>';
    }

    function _eventHref(event) {
        return '#/announcements/' + encodeURIComponent(event.event_id || event.id || '');
    }

    function _externalLink(event) {
        return event.event_page_url
            ? '<a class="oae-card-link" href="' + _esc(event.event_page_url) + '" target="_blank" rel="noopener">Details</a>'
            : '';
    }

    function _card(event) {
        var desc = event.summary || event.description || '';
        var chips = [
            event.location_name,
            event.event_types,
            event.event_audiences,
            event.registration_status
        ].map(_chip).join('');
        var badge = event.badge || 'Event';
        var colored = !!event.badge_color;
        var badgeClass = colored ? 'oae-badge oae-badge-colored' : 'oae-badge';
        var badgeStyle = colored
            ? ' style="border-color:' + _esc(event.badge_color) + ';color:' + _esc(event.badge_color) + '"'
            : '';
        return '<article class="oae-card" id="event-' + _esc(event.event_id || event.id || '') + '" data-event-id="' + _esc(event.event_id || event.id || '') + '">' +
            '<div class="oae-card-top">' +
            '<span class="' + badgeClass + '"' + badgeStyle + '>' + _esc(badge) + '</span>' +
            '<time>' + _esc(_fmtDateTime(event.start)) + '</time>' +
            '</div>' +
            '<h3><a href="' + _eventHref(event) + '">' + _esc(event.title) + '</a></h3>' +
            '<div class="oae-meta">' + _esc(event.location_name || 'Chicago Public Library') +
                (event.location_details ? ' &middot; ' + _esc(event.location_details) : '') +
                (event.location_address ? ' &middot; ' + _esc(event.location_address) : '') +
            '</div>' +
            '<p>' + _esc(desc) + '</p>' +
            '<div class="oae-card-bottom"><div class="oae-chips">' + chips + '</div>' + _externalLink(event) + '</div>' +
            '</article>';
    }

    function _detailRow(label, value) {
        if (value == null || value === '') { return ''; }
        return '<div class="oae-detail-row"><span>' + _esc(label) + '</span><strong>' + _esc(value) + '</strong></div>';
    }

    function _eventLabelList(value) {
        if (!value) { return ''; }
        return String(value).split(';').map(function(v) { return v.trim(); }).filter(Boolean).join(', ');
    }

    ogrid.AnnouncementsPage = ogrid.Class.extend({
        _container: null,
        _events: [],
        _loaded: false,
        _source: 'all',
        _pendingEventId: null,
        _expandedFocusSearch: false,
        _timer: null,
        _detailMap: null,

        init: function(container) {
            this._container = $(container || '#ogrid-announcements-page');
            this._renderShell();
            this._bind();
        },

        show: function(options) {
            options = options || {};
            this._pendingEventId = options.eventId || null;
            this._expandedFocusSearch = false;
            this._container.removeClass('hide');
            if (this._pendingEventId) {
                this.load();
                return;
            }
            this._destroyDetailMap();
            this._renderShell();
            if (!this._loaded) {
                this.load();
            } else {
                this._renderEvents();
            }
        },

        hide: function() {
            this._destroyDetailMap();
            this._container.addClass('hide');
        },

        load: function() {
            var me = this;
            var params = this._params();

            // One unified endpoint merges every source (library, sports, Navy Pier,
            // Park District) server-side; detail lookups route by id prefix there too.
            if (this._pendingEventId) {
                this._renderDetailLoading();
                $.ajax({ url: this._base() + '/events/feed', data: params, timeout: 45000 })
                    .done(function(res) {
                        var selected = ((res && res.events) || [])[0];
                        if (selected) { me._renderDetail(selected); } else { me._renderDetailMissing(); }
                    })
                    .fail(function() { me._renderDetailError(); });
                return;
            }

            $('#oae-count').html('<i class="fa fa-spinner fa-spin"></i>');
            $('#oae-feed').html('<div class="oae-empty">Loading events...</div>');

            $.ajax({ url: this._base() + '/events/feed', data: params, timeout: 45000 })
                .done(function(res) {
                    me._loaded = true;
                    me._events = (res && res.events) || [];
                    me._renderEvents();
                })
                .fail(function() {
                    $('#oae-count').text('');
                    $('#oae-feed').html('<div class="oae-empty">Events are unavailable right now.</div>');
                });
        },

        // Combine sources into one chronologically-sorted feed (kept for compatibility).
        _mergeEvents: function(a, b) {
            var all = (a || []).concat(b || []);
            all.sort(function(x, y) {
                var xs = x.start || '', ys = y.start || '';
                return xs < ys ? -1 : (xs > ys ? 1 : 0);
            });
            return all;
        },

        _base: function() {
            return ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';
        },

        _params: function() {
            var params = { limit: 300 };
            var q = $('#oae-filter').val();
            var place = $('#oae-place').val();
            var neighborhood = $('#oae-neighborhood').val();
            var from = $('#oae-date-from').val();
            var to = $('#oae-date-to').val();
            if (this._pendingEventId) {
                params.event_id = this._pendingEventId;
                params.limit = 1;
                return params;
            }
            if (this._source && this._source !== 'all') { params.source = this._source; }
            if (q) { params.q = q; }
            if (place) { params.library = place; }
            if (neighborhood) { params.neighborhood = neighborhood; }
            if (from) { params.date_from = from + 'T00:00:00'; }
            if (to) { params.date_to = to + 'T23:59:59'; }
            return params;
        },

        _renderShell: function() {
            var today = new Date();
            var nextMonth = new Date(today.getTime());
            nextMonth.setDate(nextMonth.getDate() + 30);
            this._container.html(
                '<div class="oae-page">' +
                '<header class="oae-header">' +
                '<div class="oae-brand"><i class="fa fa-th-large"></i><span>OpenGrid</span></div>' +
                '<h1>Happening in Chicago</h1>' +
                '<div class="oae-filter-wrap"><i class="fa fa-search"></i><input id="oae-filter" type="text" placeholder="Filter this feed..."></div>' +
                '</header>' +
                '<div class="oae-toolbar">' +
                '<div class="oae-tabs">' +
                '<button type="button" class="' + (this._source === 'all' ? 'active' : '') + '" data-oae-source="all">All</button>' +
                '<button type="button" class="' + (this._source === 'library' ? 'active' : '') + '" data-oae-source="library">Library</button>' +
                '<button type="button" class="' + (this._source === 'sports' ? 'active' : '') + '" data-oae-source="sports">Sports</button>' +
                '<button type="button" class="' + (this._source === 'navypier' ? 'active' : '') + '" data-oae-source="navypier">Navy Pier</button>' +
                '<button type="button" class="' + (this._source === 'parkdistrict' ? 'active' : '') + '" data-oae-source="parkdistrict">Parks</button>' +
                '</div>' +
                '<div class="oae-controls">' +
                '<input id="oae-date-from" type="date" value="' + _dateValue(today) + '">' +
                '<input id="oae-date-to" type="date" value="' + _dateValue(nextMonth) + '">' +
                '<input id="oae-place" type="text" placeholder="Library">' +
                '<input id="oae-neighborhood" type="text" placeholder="Neighborhood">' +
                '<button id="oae-clear" type="button" title="Clear filters"><i class="fa fa-times"></i></button>' +
                '</div>' +
                '<div id="oae-count"></div>' +
                '</div>' +
                '<main id="oae-feed" class="oae-feed"></main>' +
                '</div>'
            );
        },

        _bind: function() {
            var me = this;
            this._container.on('input change', '#oae-filter,#oae-place,#oae-neighborhood,#oae-date-from,#oae-date-to', function() {
                me._pendingEventId = null;
                me._expandedFocusSearch = false;
                clearTimeout(me._timer);
                me._timer = setTimeout(function() { me.load(); }, 250);
            });
            this._container.on('click', '#oae-clear', function() {
                $('#oae-filter,#oae-place,#oae-neighborhood').val('');
                $('#oae-date-from,#oae-date-to').val('');
                me.load();
            });
            this._container.on('click', '.oae-tabs button', function() {
                me._source = $(this).data('oae-source') || 'all';
                $('.oae-tabs button').removeClass('active');
                $(this).addClass('active');
                me._pendingEventId = null;
                me._expandedFocusSearch = false;
                me.load();
            });
            this._container.on('click', '.oae-card h3 a', function(e) {
                e.preventDefault();
                e.stopPropagation();
                var id = $(this).closest('.oae-card').data('event-id');
                if (ogrid.App && ogrid.App.navigateToPage) {
                    ogrid.App.navigateToPage('announce', { eventId: id });
                }
            });
            this._container.on('click', '.oae-card', function(e) {
                if ($(e.target).closest('a,button').length) {
                    return;
                }
                e.preventDefault();
                var id = $(this).closest('.oae-card').data('event-id');
                if (ogrid.App && ogrid.App.navigateToPage) {
                    ogrid.App.navigateToPage('announce', { eventId: id });
                }
            });
            this._container.on('click', '#oae-back-to-feed', function() {
                if (ogrid.App && ogrid.App.navigateToPage) {
                    ogrid.App.navigateToPage('announce');
                }
            });
            this._container.on('click', '#oae-copy-link', function() {
                var url = window.location.href;
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(url);
                }
                $(this).text('Link copied');
            });
        },

        _renderEvents: function() {
            $('#oae-count').text(this._events.length.toLocaleString() + ' event' + (this._events.length === 1 ? '' : 's'));
            if (!this._events.length) {
                $('#oae-feed').html('<div class="oae-empty">No matching events.</div>');
                return;
            }
            $('#oae-feed').html(this._events.map(_card).join(''));
        },

        _renderDetailLoading: function() {
            this._destroyDetailMap();
            this._container.html(
                '<div class="oae-page oae-detail-page">' +
                '<header class="oae-detail-header">' +
                '<button id="oae-back-to-feed" type="button" class="oae-ghost-button"><i class="fa fa-arrow-left"></i> Back</button>' +
                '<div><div class="oae-detail-kicker"><span class="oae-badge">Event</span></div>' +
                '<h1>Loading event...</h1></div>' +
                '</header>' +
                '<main class="oae-detail-empty"><i class="fa fa-spinner fa-spin"></i> Loading event details...</main>' +
                '</div>'
            );
        },

        _renderDetailMissing: function() {
            this._destroyDetailMap();
            this._container.html(
                '<div class="oae-page oae-detail-page">' +
                '<header class="oae-detail-header">' +
                '<button id="oae-back-to-feed" type="button" class="oae-ghost-button"><i class="fa fa-arrow-left"></i> Back</button>' +
                '<div><div class="oae-detail-kicker"><span class="oae-badge">Event</span></div>' +
                '<h1>Event not found</h1></div>' +
                '</header>' +
                '<main class="oae-detail-empty">This event is not available in the current library events feed.</main>' +
                '</div>'
            );
        },

        _renderDetailError: function() {
            this._destroyDetailMap();
            this._container.html(
                '<div class="oae-page oae-detail-page">' +
                '<header class="oae-detail-header">' +
                '<button id="oae-back-to-feed" type="button" class="oae-ghost-button"><i class="fa fa-arrow-left"></i> Back</button>' +
                '<div><div class="oae-detail-kicker"><span class="oae-badge">Event</span></div>' +
                '<h1>Event unavailable</h1></div>' +
                '</header>' +
                '<main class="oae-detail-empty">Event details are unavailable right now.</main>' +
                '</div>'
            );
        },

        _renderDetail: function(event) {
            var me = this;
            var chips = [
                _detailChip('place', event.location_name || 'Chicago Public Library'),
                _detailChip('type', _eventLabelList(event.event_types)),
                _detailChip('audience', _eventLabelList(event.event_audiences)),
                _detailChip('zip', event.location_zip)
            ].join('');
            var description = event.description || event.summary || 'No event description is available.';
            var colored = !!event.badge_color;
            var detailBadge = event.badge || 'Civic Event';
            var detailBadgeClass = colored ? 'oae-badge oae-badge-colored' : 'oae-badge';
            var detailBadgeStyle = colored
                ? ' style="border-color:' + _esc(event.badge_color) + ';color:' + _esc(event.badge_color) + '"'
                : '';
            var sourceFeed = colored ? (event.source || 'Events') : 'Chicago Public Library Events';
            var sourceLink = event.event_page_url
                ? '<a class="oae-source-link" href="' + _esc(event.event_page_url) + '" target="_blank" rel="noopener">View original event <i class="fa fa-external-link"></i></a>'
                : '';

            this._destroyDetailMap();
            this._container.html(
                '<div class="oae-page oae-detail-page">' +
                '<header class="oae-detail-header">' +
                '<button id="oae-back-to-feed" type="button" class="oae-ghost-button"><i class="fa fa-arrow-left"></i> Back</button>' +
                '<div class="oae-detail-title-wrap">' +
                '<div class="oae-detail-kicker"><span class="' + detailBadgeClass + '"' + detailBadgeStyle + '>' + _esc(detailBadge) + '</span><span>' + _esc(_fmtRange(event)) + '</span></div>' +
                '<h1>' + _esc(event.title || 'Library Event') + '</h1>' +
                '</div>' +
                '<div class="oae-detail-actions">' +
                '<button id="oae-copy-link" type="button" class="oae-ghost-button"><i class="fa fa-link"></i> Copy link</button>' +
                '<button type="button" class="oae-primary-button"><i class="fa fa-bell"></i> Subscribe</button>' +
                '</div>' +
                '</header>' +
                '<main class="oae-detail-layout">' +
                '<section class="oae-detail-main">' +
                '<div class="oae-affects-label">Affects</div>' +
                '<div class="oae-affects">' + chips + '</div>' +
                '<article class="oae-detail-card">' +
                '<h2>Event Details</h2>' +
                '<p>' + _esc(description) + '</p>' +
                '<div class="oae-detail-rows">' +
                _detailRow('When', _fmtRange(event)) +
                _detailRow('Where', [event.location_name, event.location_details].filter(Boolean).join(' · ')) +
                _detailRow('Address', event.location_address) +
                _detailRow('Registration', event.registration_status || (event.registration_closed ? 'Closed' : '')) +
                _detailRow('Language', _eventLabelList(event.event_languages)) +
                _detailRow('Recurring', event.recurring ? 'Yes' : '') +
                '</div>' +
                '</article>' +
                '</section>' +
                '<aside class="oae-detail-side">' +
                '<div class="oae-location-card"><div id="oae-detail-map"></div><span>event location</span></div>' +
                '<article class="oae-source-card">' +
                '<div class="oae-source-label">Source · Provenance</div>' +
                '<h2>' + _esc(event.source || 'Chicago Public Library') + '</h2>' +
                '<div class="oae-source-muted">' + _esc(sourceFeed) + '</div>' +
                '<div class="oae-source-tags"><span>city data</span><span>source-linked</span></div>' +
                sourceLink +
                '</article>' +
                '</aside>' +
                '</main>' +
                '</div>'
            );
            window.setTimeout(function() { me._renderDetailMap(event); }, 40);
        },

        _destroyDetailMap: function() {
            if (this._detailMap) {
                try { this._detailMap.remove(); } catch (e) {}
                this._detailMap = null;
            }
        },

        _renderDetailMap: function(event) {
            var lat = Number(event && event.lat);
            var lon = Number(event && event.lon);
            var el = document.getElementById('oae-detail-map');
            if (!el || !window.L) { return; }
            if (isNaN(lat) || isNaN(lon)) {
                el.innerHTML = '<div class="oae-map-empty">No mapped location</div>';
                return;
            }
            this._destroyDetailMap();
            var map = L.map(el, {
                zoomControl: false,
                attributionControl: false,
                dragging: false,
                scrollWheelZoom: false,
                doubleClickZoom: false,
                boxZoom: false,
                keyboard: false,
                touchZoom: false,
                tap: false
            });
            this._detailMap = map;
            var base = ((ogrid.Config.map || {}).baseLayers || [])[0];
            if (base && base.url) {
                L.tileLayer(base.url, $.extend({}, base.options || {}, {
                    attribution: '',
                    opacity: 0.84
                })).addTo(map);
            }
            L.circleMarker([lat, lon], {
                radius: 8,
                color: '#c65f24',
                weight: 3,
                fillColor: '#c65f24',
                fillOpacity: 0.85
            }).addTo(map);
            map.setView([lat, lon], 15, { animate: false });
            map.invalidateSize(false);
        },

        _focusEvent: function(eventId) {
            var me = this;
            window.setTimeout(function() {
                var $card = $('#event-' + eventId);
                if (!$card.length) {
                    if (me._expandedFocusSearch) {
                        return;
                    }
                    me._expandedFocusSearch = true;
                    $('#oae-filter').val('');
                    $('#oae-place').val('');
                    $('#oae-neighborhood').val('');
                    $('#oae-date-from').val('');
                    $('#oae-date-to').val('');
                    me._pendingEventId = eventId;
                    me.load();
                    return;
                }
                $('.oae-card').removeClass('focused');
                $card.addClass('focused');
                $card[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 40);
        }
    });

    ogrid.announcementsPage = function() {
        if (!_instance) {
            _instance = new ogrid.AnnouncementsPage('#ogrid-announcements-page');
        }
        return _instance;
    };
}());

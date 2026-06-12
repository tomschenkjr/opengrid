/*
 * ogrid.CommunityProfile
 *
 * Community Trends panel: headline ACS indicators + citywide comparison for a single
 * Chicago community area. Rendered into #ogrid-community-profile. Reached two ways —
 * the sidebar "Community Trends" item (with a dropdown selector) and clicking a
 * community-area label on the map (ogrid.communityProfile().load(number)).
 *
 * Backend: GET /geography/community-areas            (selector list)
 *          GET /geography/community-areas/{n}/profile (KPIs + comparison)
 */
ogrid.CommunityProfile = ogrid.Class.extend({

    _container: null,
    _built: false,
    _areasLoaded: false,
    _current: null,

    init: function(options) {
        this._options = options || {};
        this._container = $('#ogrid-community-profile');
        this._charts = [];          // live Chart.js instances (destroyed on reload)
        this._pendingCharts = [];   // chart specs awaiting DOM insertion
        this._chartSeq = 0;         // unique canvas id counter
        this._summarySeq = 0;       // guards async summary responses during area switches
        this._miniMap = null;
    },

    _endpoint: function() {
        return (this._options.endpoint || ogrid.Config.service.endpoint).replace(/\/$/, '');
    },

    _authHeaders: function() {
        var token = (typeof sessionStorage !== 'undefined') ? sessionStorage.getItem('auth_token') : null;
        return token ? { 'X-AUTH-TOKEN': token } : {};
    },

    // Build the static chrome (header + selector) once.
    _build: function() {
        if (this._built) { return; }
        var me = this;
        this._container.html(
            '<div class="ocp-page">' +
              '<div class="ocp-header">' +
                '<div class="ocp-title"><i class="fa fa-bar-chart"></i> Community Trends</div>' +
                '<div class="ocp-area-picker">' +
                  '<label for="ocp-area-select">Community area</label>' +
                  '<select id="ocp-area-select" class="ocp-area-select"></select>' +
                '</div>' +
              '</div>' +
              '<div id="ocp-body" class="ocp-body">' +
                '<div class="ocp-empty">Select a community area to see its profile.</div>' +
              '</div>' +
            '</div>'
        );
        $('#ocp-area-select').on('change', function() {
            var val = $(this).val();
            if (val === 'chicago') { me.load('chicago'); return; }
            var num = parseInt(val, 10);
            if (num) { me.load(num); }
        });
        this._built = true;
        this._loadAreas();
    },

    _loadAreas: function() {
        if (this._areasLoaded) { return; }
        var me = this;
        $.ajax({
            url: this._endpoint() + '/geography/community-areas',
            type: 'GET',
            headers: this._authHeaders(),
            success: function(areas) {
                var $sel = $('#ocp-area-select');
                $sel.empty().append('<option value="">— choose —</option>');
                $sel.append('<option value="chicago">Chicago (Citywide)</option>');
                (areas || []).forEach(function(a) {
                    $sel.append('<option value="' + a.number + '">' + a.name + '</option>');
                });
                me._areasLoaded = true;
                // If a profile was requested before the list arrived, reflect it now.
                if (me._current) { $sel.val(String(me._current)); }
            },
            error: function() {
                $('#ocp-body').html('<div class="ocp-empty">Could not load the community-area list.</div>');
            }
        });
    },

    show: function() {
        this._build();
        this._container.removeClass('hide');
        if (!this._current) { this.load('chicago'); }
    },

    hide: function() {
        this._container.addClass('hide');
    },

    // Load and render the profile for a community area number, or 'chicago' for citywide.
    load: function(number) {
        var me = this;
        this._build();
        this._current = number;
        this._destroyCharts();
        this._destroyMiniMap();
        if (this._areasLoaded) {
            $('#ocp-area-select').val(number === 'chicago' ? 'chicago' : String(number));
        }
        $('#ocp-body').html('<div class="ocp-loading"><i class="fa fa-spinner fa-spin"></i> Loading…</div>');

        var seg = (number === 'chicago') ? 'chicago' : number;
        $.ajax({
            url: this._endpoint() + '/geography/community-areas/' + seg + '/profile',
            type: 'GET',
            headers: this._authHeaders(),
            success: function(data) { me._render(data); },
            error: function() {
                $('#ocp-body').html('<div class="ocp-empty">Could not load this community profile.</div>');
            }
        });
    },

    _render: function(data) {
        if (!data || data.available === false) {
            var msg = (data && data.message) || 'Census data unavailable for this community area.';
            $('#ocp-body').html(
                '<div class="ocp-area-name">' + ((data && data.name) || '') + '</div>' +
                '<div class="ocp-empty">' + msg + '</div>'
            );
            return;
        }

        var meta = (data.number != null)
            ? 'Community Area ' + data.number + ' · ACS ' + data.acs_year + ' (5-yr)'
            : 'ACS ' + data.acs_year + ' (5-yr)';
        var html =
            '<div class="ocp-area-head">' +
              '<div class="ocp-area-name">' + data.name + '</div>' +
              '<div class="ocp-area-meta">' + meta + '</div>' +
            '</div>' +
            this._renderOverview(data) +
            this._renderKpis(data.kpis) +
            this._renderSections(data.sections);

        $('#ocp-body').html(html);
        this._instantiateCharts();
        if (data.number != null) { this._renderBoundaryMap(data.boundary); }
        this._loadSummary(data.number);
    },

    _renderOverview: function(data) {
        var boundaryCard = (data.number != null)
            ? '<div class="ocp-boundary-card">' +
                '<div id="ocp-boundary-map" class="ocp-boundary-map"></div>' +
                '<div class="ocp-boundary-label">Community Area ' + this._esc(data.number) + '</div>' +
              '</div>'
            : '';
        return '<div class="ocp-overview-row">' +
                 '<div class="ocp-summary-card">' +
                   '<div class="ocp-summary-title">About ' + this._esc(data.name) + '</div>' +
                   '<div class="ocp-summary-sub">What the numbers say about this community</div>' +
                   '<div id="ocp-ai-summary" class="ocp-ai-summary">' +
                     '<i class="fa fa-spinner fa-spin"></i> Reading the profile…' +
                   '</div>' +
                 '</div>' +
                 boundaryCard +
               '</div>';
    },

    _loadSummary: function(number) {
        var me = this;
        var seq = ++this._summarySeq;
        var seg = (number == null) ? 'chicago' : number;
        $.ajax({
            url: this._endpoint() + '/geography/community-areas/' + seg + '/profile/summary',
            type: 'GET',
            headers: this._authHeaders(),
            timeout: 45000,
            success: function(data) {
                if (seq !== me._summarySeq) { return; }
                $('#ocp-ai-summary').html(me._summaryHtml((data && data.summary) || 'Summary unavailable.'));
            },
            error: function() {
                if (seq !== me._summarySeq) { return; }
                $('#ocp-ai-summary').html('Summary unavailable right now.');
            }
        });
    },

    _renderBoundaryMap: function(geometry) {
        var el = document.getElementById('ocp-boundary-map');
        if (!el || !geometry || !window.L) {
            if (el) { el.innerHTML = '<div class="ocp-boundary-empty">No outline</div>'; }
            return;
        }

        this._destroyMiniMap();
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
        this._miniMap = map;

        var base = ((ogrid.Config.map || {}).baseLayers || [])[0];
        if (base && base.url) {
            L.tileLayer(base.url, $.extend({}, base.options || {}, {
                attribution: '',
                opacity: 0.82
            })).addTo(map);
        }

        var layer = L.geoJson({ type: 'Feature', geometry: geometry }, {
            style: {
                color: '#2f77be',
                weight: 3,
                opacity: 1,
                fillColor: '#2f77be',
                fillOpacity: 0.18
            },
            interactive: false
        }).addTo(map);

        try {
            map.fitBounds(layer.getBounds(), { padding: [18, 18], animate: false });
        } catch (e) {
            map.setView([41.8781, -87.6298], 10);
        }
        setTimeout(function() {
            try { map.invalidateSize(false); } catch (e) {}
        }, 0);
    },

    _summaryHtml: function(text) {
        var parts = String(text || '').split(/\n+/).map(function(p) {
            return $.trim(p);
        }).filter(Boolean);
        if (!parts.length) {
            return 'Summary unavailable.';
        }
        return parts.map(function(p) {
            return '<p>' + this._esc(p) + '</p>';
        }, this).join('');
    },

    // --- Sectioned report (Demographics / Economics / ...) ----------------- #
    _renderSections: function(sections) {
        var me = this;
        this._pendingCharts = [];
        if (!sections || !sections.length) { return ''; }
        return sections.map(function(sec) {
            var groups = sec.groups.map(function(grp) {
                var items = grp.items.map(function(it) { return me._renderItem(it); }).join('');
                var title = grp.title ? '<div class="ocp-group-title">' + grp.title + '</div>' : '';
                return '<div class="ocp-group">' +
                         title +
                         '<div class="ocp-group-items">' + items + '</div>' +
                       '</div>';
            }).join('');
            return '<div class="ocp-section">' +
                     '<div class="ocp-section-rail"><span>' + sec.title + '</span></div>' +
                     '<div class="ocp-section-content">' + groups + '</div>' +
                   '</div>';
        }).join('');
    },

    _renderItem: function(it) {
        switch (it.type) {
            case 'stat':
                return this._statBlock(it.label, it.value, it.format, it.unit);
            case 'stat_list':
                return it.items.map(function(s) {
                    return this._statBlock(s.label, s.value, s.format, s.unit);
                }, this).join('');
            case 'pie':
                return this._chartBlock(it.label, 'pie', { slices: it.slices });
            case 'histogram':
            case 'column':
                return this._chartBlock(it.label, it.type,
                    { bins: it.bins, percent: (it.type === 'histogram') });
            case 'grouped_column':
                return this._chartBlock(it.label, 'grouped',
                    { categories: it.categories, series: it.series });
            case 'stacked_column':
                return this._chartBlock(it.label, 'stacked',
                    { segments: it.segments });
            case 'line':
                return this._chartBlock(it.label, 'line',
                    { points: it.points, format: it.format });
            case 'box_whisker':
                return this._chartBlock(it.label, 'boxWhisker',
                    { value: it.value, distribution: it.distribution, format: it.format });
            default:
                return '';
        }
    },

    _statBlock: function(label, value, fmt, unit) {
        var v = this._format(value, fmt);
        var u = unit ? ' <span class="ocp-stat-unit">' + unit + '</span>' : '';
        return '<div class="ocp-item ocp-stat">' +
                 '<div class="ocp-stat-value">' + v + u + '</div>' +
                 '<div class="ocp-stat-label">' + label + '</div>' +
               '</div>';
    },

    _chartBlock: function(label, kind, data) {
        var id = 'ocp-chart-' + (++this._chartSeq);
        this._pendingCharts.push({ id: id, kind: kind, data: data });
        return '<div class="ocp-item ocp-chart">' +
                 '<div class="ocp-item-label">' + label + '</div>' +
                 '<div class="ocp-canvas-wrap"><canvas id="' + id + '"></canvas></div>' +
               '</div>';
    },

    _instantiateCharts: function() {
        var me = this;
        (this._pendingCharts || []).forEach(function(spec) {
            var canvas = document.getElementById(spec.id);
            if (!canvas || !window.Chart || !ogrid.ProfileCharts) { return; }
            var chart = null;
            try {
                if (spec.kind === 'pie') {
                    chart = ogrid.ProfileCharts.pie(canvas, spec.data.slices);
                } else if (spec.kind === 'grouped') {
                    chart = ogrid.ProfileCharts.groupedBars(canvas, spec.data.categories, spec.data.series);
                } else if (spec.kind === 'stacked') {
                    chart = ogrid.ProfileCharts.stackedColumn(canvas, spec.data.segments);
                } else if (spec.kind === 'line') {
                    chart = ogrid.ProfileCharts.line(canvas, spec.data.points, { format: spec.data.format });
                } else if (spec.kind === 'boxWhisker') {
                    chart = ogrid.ProfileCharts.boxWhisker(canvas, spec.data);
                } else {
                    chart = ogrid.ProfileCharts.bars(canvas, spec.data.bins, { percent: spec.data.percent });
                }
            } catch (e) { /* skip a chart that fails to build */ }
            if (chart) { me._charts.push(chart); }
        });
        this._pendingCharts = [];
    },

    _destroyCharts: function() {
        (this._charts || []).forEach(function(c) { try { c.destroy(); } catch (e) {} });
        this._charts = [];
    },

    _destroyMiniMap: function() {
        if (this._miniMap) {
            try { this._miniMap.remove(); } catch (e) {}
            this._miniMap = null;
        }
    },

    _renderKpis: function(kpis) {
        var me = this;
        if (!kpis || !kpis.length) { return ''; }
        var cards = kpis.map(function(k) {
            var value = me._format(k.value, k.format);
            var context = (k.citywide != null)
                ? '<div class="ocp-kpi-context">Chicago: ' + me._format(k.citywide, k.format) + '</div>'
                : '';
            return (
                '<div class="ocp-kpi-card">' +
                  '<div class="ocp-kpi-label">' + k.label + '</div>' +
                  '<div class="ocp-kpi-value">' + value + '</div>' +
                  context +
                '</div>'
            );
        }).join('');
        return '<div class="ocp-kpi-grid">' + cards + '</div>';
    },

    _format: function(value, fmt) {
        if (value == null) { return '—'; }
        switch (fmt) {
            case 'currency':
                return '$' + Math.round(value).toLocaleString();
            case 'percent':
                return Math.round(value) + '%';
            case 'decimal':
                return (Math.round(value * 10) / 10).toFixed(1);
            case 'count':
                if (value >= 10000) { return (Math.round(value / 100) / 10) + 'k'; }
                return Math.round(value).toLocaleString();
            default:
                return String(value);
        }
    },

    _esc: function(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
});

// Lazily-created singleton so map-label clicks and the sidebar share one instance.
ogrid._communityProfile = null;
ogrid.communityProfile = function() {
    if (!ogrid._communityProfile) {
        ogrid._communityProfile = new ogrid.CommunityProfile();
    }
    return ogrid._communityProfile;
};

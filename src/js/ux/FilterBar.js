/*
 * ogrid.FilterBar
 *
 * Filter chiclets shown above the results list: timeframe, neighborhood
 * (Chicago community areas), and dataset. Changing a chiclet re-runs the
 * search server-side via POST /search/filtered and re-renders through the
 * existing QSearch rendering pipeline.
 */
ogrid.FilterBar = ogrid.Class.extend({

    _options: {},
    _state: { datasets: [], timeframe: 'all', community_area: null },

    _timeframes: [
        { v: 'all',          l: 'All time' },
        { v: 'this-year',    l: 'This year' },
        { v: 'last-year',    l: 'Last year' },
        { v: 'last-90-days', l: 'Last 90 days' },
        { v: 'last-60-days', l: 'Last 60 days' },
        { v: 'last-7-days',  l: 'Last 7 days' }
    ],

    init: function(options) {
        if (options) { this._options = $.extend(this._options, options); }
        var me = this;

        this._render();
        this._loadCommunityAreas();

        // Toggle menus
        $('#ogrid-filter-bar').on('click', '.ogrid-chiclet > button', function(e) {
            e.stopPropagation();
            var $c = $(this).closest('.ogrid-chiclet');
            var wasOpen = $c.hasClass('open');
            $('#ogrid-filter-bar .ogrid-chiclet').removeClass('open');
            if (!wasOpen) $c.addClass('open');
        });
        // Select an option
        $('#ogrid-filter-bar').on('click', '.ogrid-chiclet-menu button', function(e) {
            e.stopPropagation();
            var $c = $(this).closest('.ogrid-chiclet');
            me._onSelect($c.data('key'), $(this).data('value'), $(this).text());
            $c.removeClass('open');
        });
        // Close on outside click
        $(document).on('click', function() {
            $('#ogrid-filter-bar .ogrid-chiclet').removeClass('open');
        });
    },

    // ---- build chiclets ---------------------------------------------------
    _render: function() {
        var tf = this._menu(this._timeframes.map(function(t) {
            return { value: t.v, label: t.l };
        }));
        var datasetItems = (this._options.datasets || []).map(function(d) {
            return { value: d.id, label: d.displayName };
        });
        $('#ogrid-filter-bar').html(
            this._chiclet('timeframe', 'All time', tf) +
            this._chiclet('neighborhood', 'All neighborhoods',
                '<div class="ogrid-loading" style="padding:8px;color:#6b7785">Loading…</div>') +
            this._chiclet('datasets', 'Dataset', this._menu(datasetItems))
        );
    },

    _chiclet: function(key, label, menuHtml) {
        return '<div class="ogrid-chiclet" data-key="' + key + '">' +
               '<button><span class="lbl">' + label + '</span>' +
               '<span class="caret"><i class="fa fa-caret-down"></i></span></button>' +
               '<div class="ogrid-chiclet-menu">' + menuHtml + '</div></div>';
    },

    _menu: function(items) {
        return items.map(function(it) {
            return '<button data-value="' + (it.value == null ? '' : it.value) + '">' +
                   it.label + '</button>';
        }).join('');
    },

    _loadCommunityAreas: function() {
        var me = this;
        var apply = function(list) {
            var items = [{ value: '', label: 'All neighborhoods' }].concat(
                list.map(function(c) { return { value: c.number, label: c.name }; })
            );
            $('#ogrid-filter-bar .ogrid-chiclet[data-key="neighborhood"] .ogrid-chiclet-menu')
                .html(me._menu(items));
        };
        if (ogrid.App && ogrid.App._communityAreas) { apply(ogrid.App._communityAreas); return; }
        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/geography/community-areas';
        $.ajax({ url: url, type: 'GET', timeout: 12000 })
            .done(function(list) { if (ogrid.App) ogrid.App._communityAreas = list; apply(list); })
            .fail(function() {
                $('#ogrid-filter-bar .ogrid-chiclet[data-key="neighborhood"] .ogrid-chiclet-menu')
                    .html('<div style="padding:8px;color:#6b7785">Unavailable</div>');
            });
    },

    // ---- state sync (no re-query) ----------------------------------------
    syncFromMeta: function(filters) {
        if (!filters) return;
        this._state.datasets = filters.dataset_id ? [filters.dataset_id] : [];
        this._state.timeframe = filters.timeframe || 'all';
        this._state.community_area = filters.community_area ? filters.community_area.number : null;

        var tfLabel = 'All time', tf = this._state.timeframe;
        for (var i = 0; i < this._timeframes.length; i++) {
            if (this._timeframes[i].v === tf) { tfLabel = this._timeframes[i].l; break; }
        }
        this._setLabel('timeframe', tfLabel);
        this._setLabel('neighborhood', filters.community_area ? filters.community_area.name : 'All neighborhoods');
        this._setLabel('datasets', filters.dataset_name || 'Dataset');
    },

    _setLabel: function(key, label) {
        $('#ogrid-filter-bar .ogrid-chiclet[data-key="' + key + '"] .lbl').text(label);
    },

    // ---- user changed a filter -------------------------------------------
    _onSelect: function(key, value, label) {
        if (key === 'timeframe') {
            this._state.timeframe = value || 'all';
        } else if (key === 'neighborhood') {
            this._state.community_area = value ? parseInt(value, 10) : null;
        } else if (key === 'datasets') {
            this._state.datasets = value ? [value] : [];
        }
        this._setLabel(key, label);
        this._run();
    },

    _run: function() {
        var me = this;
        if (!this._state.datasets.length) return;

        var bounds = null;
        try {
            var b = ogrid.App.map().getMap().getBounds();
            bounds = { minLat: b.getSouth(), minLon: b.getWest(), maxLat: b.getNorth(), maxLon: b.getEast() };
        } catch (e) {}

        var payload = {
            datasets: this._state.datasets,
            timeframe: this._state.timeframe,
            community_area: this._state.community_area,
            bounds: bounds
        };
        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/search/filtered';
        var token = (typeof sessionStorage !== 'undefined') ? sessionStorage.getItem('auth_token') : null;

        $.ajax({
            url: url, type: 'POST', contentType: 'application/json',
            data: JSON.stringify(payload),
            headers: token ? { 'X-AUTH-TOKEN': token } : {},
            timeout: 60000
        }).done(function(res) {
            // Reuse the existing render pipeline (map + ResultsPanel + summarize)
            if (ogrid.App && ogrid.App._qs) { ogrid.App._qs._onExecDone(res); }
        }).fail(function() {
            ogrid.Alert.error('Unable to apply filter.');
        });
    }
});

ogrid.filterBar = function(options) { return new ogrid.FilterBar(options); };

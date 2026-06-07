/*
 * ogrid.ResultsPanel
 *
 * Left-docked results list. Two render modes:
 *  - records mode (single-dataset search): the FULL result set, lazy-paged from
 *    /search/records (200 at a time on scroll) with a "Showing X of N" header.
 *  - feature mode (POI / MCP zone / multi-dataset / boundary): renders the
 *    features carried in the REFRESH_DATA payload directly (small sets).
 * Also renders persistent-station detail (showStationContent) on its own path.
 */
ogrid.ResultsPanel = ogrid.Class.extend({

    _options: {},
    _PAGE: 200,

    init: function(options) {
        if (options) { this._options = $.extend(this._options, options); }
        var me = this;

        this._mode = 'features';
        this._featureLayers = [];
        this._context = null;
        this._primaryCount = 0;
        this._rec = null;          // {total, loaded, columns, roles, color}
        this._loading = false;
        this._sort = 'newest';

        ogrid.Event.on(ogrid.Event.types.REFRESH_DATA, $.proxy(this._onRefresh, this));
        ogrid.Event.on(ogrid.Event.types.CLEAR, $.proxy(this._onClear, this));
        ogrid.Event.on(ogrid.Event.types.FEATURE_SELECTED, $.proxy(this._onFeatureSelected, this));

        $('#ogrid-sort-wrapper').html(
            '<select id="ogrid-sort-select">' +
            '<option value="newest">Sort: Newest</option>' +
            '<option value="oldest">Sort: Oldest</option>' +
            '</select>'
        );
        $('#ogrid-sort-wrapper').on('change', '#ogrid-sort-select', function() {
            me._sort = this.value;
            if (me._mode === 'records' && me._context) { me._loadRecords(true); }
            else { me._renderFeatures(); }
        });

        $('#ogrid-results-collapse').on('click', function() { $('#ogrid-container').addClass('results-collapsed'); });
        $('#ogrid-results-reopen').on('click', function() { $('#ogrid-container').removeClass('results-collapsed'); });

        // Lazy paging on scroll (records mode)
        $('#ogrid-results-list').on('scroll', function() {
            if (me._mode !== 'records') return;
            var el = this;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 240) { me._loadMore(); }
        });

        // Card click → details + map
        $('#ogrid-results-list').on('click', '.ogrid-result-card', function() {
            $(this).toggleClass('expanded');
            me._cardToMap($(this));
        });
    },

    _onClear: function() {
        this._featureLayers = [];
        this._context = null;
        this._primaryCount = 0;
        this._rec = null;
        this._mode = 'features';
        $('#ogrid-container').removeClass('results-collapsed');
        $('#ogrid-results-panel').addClass('hide').removeClass('station-mode');
        $('#ogrid-results-list').empty();
        $('#ogrid-trend-card').empty();
        $('#ogrid-results-count').empty();
    },

    _isPrimaryLayer: function(data) {
        var view = data && data.meta && data.meta.view;
        if (!view || !view.id) return false;
        return view.id.indexOf('boundary-') !== 0 && view.id.indexOf('proximity-') !== 0;
    },

    _onRefresh: function(evt) {
        var msg = evt.message || {};
        var data = msg.data;
        if (!data) return;
        if (msg.options && msg.options.passthroughData && msg.options.passthroughData.mapModeSwap) return;

        if (msg.options && msg.options.clear) {
            this._featureLayers = [];
            this._context = null;
            this._primaryCount = 0;
            this._rec = null;
        }

        var filters = data.meta && data.meta.filters;
        if (filters) {
            this._primaryCount++;
            if (this._primaryCount === 1) {
                this._context = {
                    dataset: filters.dataset_id,
                    dataset_name: filters.dataset_name,
                    timeframe: filters.timeframe || 'all',
                    community_area: filters.community_area ? filters.community_area.number : null,
                    soql_where: filters.soql_where || null
                };
            } else {
                this._context = null;   // multi-dataset → feature mode
            }
            if (ogrid.App && ogrid.App._filterBar) { ogrid.App._filterBar.syncFromMeta(filters); }
        }

        if (this._isPrimaryLayer(data) && data.features) {
            this._featureLayers.push({ rsId: msg.resultSetId, data: data });
        }

        this._showPanel();
        // Single dataset with filter context → full paged record list; else features.
        if (this._context && this._primaryCount === 1) {
            this._loadRecords(true);
        } else {
            this._renderFeatures();
        }
    },

    _showPanel: function() {
        $('#ogrid-results-panel').removeClass('hide').removeClass('station-mode');
        $('#ogrid-container').removeClass('viewing-section').removeClass('results-collapsed');
        $('#ogrid-section-placeholder').addClass('hide');
        $('#ogrid-sidebar .ogrid-nav-item').removeClass('active').filter('[data-section="search"]').addClass('active');
    },

    // ---- column roles + formatting ---------------------------------------
    _colByRole: function(cols) {
        var roles = { date: null, status: null, addr: null, title: null };
        var statusIds = ['status', 'results', 'arrest', 'risk'];
        var addrIds = ['block', 'address', 'street_address', 'location_description', 'street_name'];
        $.each(cols, function(i, c) {
            if (!roles.date && c.dataType === 'date') roles.date = c;
            if (!roles.status && statusIds.indexOf(c.id) !== -1) roles.status = c;
            if (!roles.addr && addrIds.indexOf(c.id) !== -1) roles.addr = c;
        });
        $.each(cols, function(i, c) {
            if (roles.title) return;
            if (c === roles.date || c === roles.status || c === roles.addr) return;
            if (c.dataType === 'string' && (c.list || c.popup)) roles.title = c;
        });
        if (!roles.title) roles.title = cols[0] || null;
        return roles;
    },

    _relTime: function(val) {
        if (!val) return '';
        try { return moment(val).fromNow(); } catch (e) { return String(val).substring(0, 10); }
    },

    _esc: function(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    _datasetColor: function(datasetId) {
        try {
            var ds = (ogrid.App._datasets || []).filter(function(d) { return d.id === datasetId; })[0];
            return ds.options.rendition.color;
        } catch (e) { return '#1565C0'; }
    },

    // ---- records mode (lazy paged) ---------------------------------------
    _loadRecords: function(reset) {
        var me = this;
        if (!this._context) return;
        this._mode = 'records';
        if (reset) {
            this._rec = { total: 0, loaded: 0, columns: [], roles: null,
                          color: this._datasetColor(this._context.dataset) };
            $('#ogrid-results-list').empty().scrollTop(0);
        }
        this._fetchPage(0, true);
    },

    _loadMore: function() {
        if (!this._rec || this._loading) return;
        if (this._rec.loaded >= this._rec.total) return;
        this._fetchPage(this._rec.loaded, false);
    },

    _fetchPage: function(offset, isFirst) {
        var me = this;
        if (this._loading) return;
        this._loading = true;

        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/search/records';
        var token = (typeof sessionStorage !== 'undefined') ? sessionStorage.getItem('auth_token') : null;
        var payload = $.extend({}, this._context, {
            offset: offset, limit: this._PAGE,
            order: this._sort   // server defaults to newest; oldest handled below
        });

        $.ajax({
            url: url, type: 'POST', contentType: 'application/json',
            data: JSON.stringify(payload),
            headers: token ? { 'X-AUTH-TOKEN': token } : {},
            timeout: 30000
        }).done(function(res) {
            me._loading = false;
            if (me._mode !== 'records') return;
            me._rec.total = res.total || 0;
            me._rec.columns = res.columns || [];
            me._rec.roles = me._colByRole(me._rec.columns);

            var records = res.records || [];
            var html = records.map(function(row) { return me._cardHtml(row, me._rec.columns, me._rec.roles, me._rec.color); }).join('');
            $('#ogrid-results-list').append(html);
            me._rec.loaded += records.length;

            me._updateCountHeader(me._rec.loaded, me._rec.total);
            me._updateTrend(me._rec.total);
        }).fail(function() {
            me._loading = false;
            if (isFirst) { $('#ogrid-results-list').html('<div class="ogrid-empty">Unable to load records.</div>'); }
        });
    },

    _updateCountHeader: function(loaded, total) {
        if (loaded >= total) {
            $('#ogrid-results-count').html('<b>' + total.toLocaleString() + '</b> result' + (total === 1 ? '' : 's'));
        } else {
            $('#ogrid-results-count').html('Showing <b>' + loaded.toLocaleString() + '</b> of ' + total.toLocaleString());
        }
    },

    _updateTrend: function(total) {
        $('#ogrid-trend-card').html(
            '<div class="ogrid-trend">' +
            '<div><div class="big">' + total.toLocaleString() + '</div><div class="lbl">results</div></div>' +
            '<div><div class="delta">—</div><div class="lbl">vs prior period</div></div>' +
            '</div>'
        );
    },

    // ---- feature mode (POI / MCP / multi-dataset) ------------------------
    _renderFeatures: function() {
        var me = this;
        this._mode = 'features';
        var $list = $('#ogrid-results-list');
        var rows = [];
        $.each(this._featureLayers, function(li, layer) {
            var view = layer.data.meta.view;
            var roles = me._colByRole(view.columns || []);
            var color = (view.options && view.options.rendition && view.options.rendition.color) || '#1565C0';
            $.each(layer.data.features || [], function(fi, f) {
                rows.push({ props: f.properties || {}, cols: view.columns || [], roles: roles,
                            color: color, rsId: layer.rsId, oid: ogrid.oid(f) });
            });
        });

        if (!rows.length) {
            if (this._featureLayers.length) {
                $list.html('<div class="ogrid-empty">No matching records.</div>');
                $('#ogrid-results-count').html('<b>0</b> results');
                $('#ogrid-trend-card').empty();
            }
            return;
        }
        rows.sort(function(a, b) {
            var av = a.roles.date ? a.props[a.roles.date.id] : null;
            var bv = b.roles.date ? b.props[b.roles.date.id] : null;
            if (!av && !bv) return 0; if (!av) return 1; if (!bv) return -1;
            return me._sort === 'newest' ? (av < bv ? 1 : -1) : (av < bv ? -1 : 1);
        });
        $list.html(rows.map(function(r) {
            return me._cardHtml(r.props, r.cols, r.roles, r.color, r.rsId, r.oid);
        }).join(''));
        this._updateCountHeader(rows.length, rows.length);
        this._updateTrend(rows.length);
    },

    // ---- shared card builder ---------------------------------------------
    _cardHtml: function(props, cols, roles, color, rsId, oid) {
        props = props || {};
        var title = roles.title ? this._esc(props[roles.title.id]) : 'Record';
        if (!title) title = 'Record';
        var pill = roles.status && props[roles.status.id] != null
            ? '<span class="rc-pill">' + this._esc(props[roles.status.id]) + '</span>' : '';
        var subParts = [];
        if (roles.addr && props[roles.addr.id]) subParts.push(this._esc(props[roles.addr.id]));
        if (roles.date && props[roles.date.id]) subParts.push(this._relTime(props[roles.date.id]));
        var sub = subParts.join(' · ');

        var lat = props.latitude || props.school_latitude || '';
        var lon = props.longitude || props.school_longitude || '';

        var details = (cols || []).filter(function(c) { return c.popup; });
        if (!details.length) details = cols || [];
        var me = this;
        var detailRows = details.map(function(c) {
            var v = props[c.id];
            if (v == null || v === '') return '';
            return '<div class="rc-row"><span class="rc-k">' + me._esc(c.displayName) + '</span>' +
                   '<span class="rc-v">' + me._esc(v) + '</span></div>';
        }).filter(Boolean).join('');

        return '<div class="ogrid-result-card" style="border-left-color:' + (color || '#1565C0') + '" ' +
               'data-rsid="' + this._esc(rsId == null ? '' : rsId) + '" ' +
               'data-oid="' + this._esc(oid == null ? '' : oid) + '" ' +
               'data-lat="' + this._esc(lat) + '" data-lon="' + this._esc(lon) + '">' +
               '<div class="rc-top"><div class="rc-title">' + title + '</div>' +
               '<div class="rc-top-right">' + pill +
               '<button type="button" class="rc-toggle" aria-label="Toggle details"><i class="fa fa-chevron-down"></i></button>' +
               '</div></div>' +
               (sub ? '<div class="rc-sub">' + sub + '</div>' : '') +
               '<div class="rc-details">' + (detailRows || '<div class="rc-row">No additional details.</div>') + '</div>' +
               '</div>';
    },

    _cardToMap: function($card) {
        var rsId = $card.attr('data-rsid');
        var oid = $card.attr('data-oid');
        // Prefer an existing map marker (feature mode)
        if (rsId && oid) {
            try { this._options.map.popupMarkerByLatLng(rsId, oid); return; } catch (e) {}
        }
        // Otherwise pan to the record's location (records mode / no marker)
        var lat = parseFloat($card.attr('data-lat')), lon = parseFloat($card.attr('data-lon'));
        if (!isNaN(lat) && !isNaN(lon)) {
            try {
                var map = this._options.map.getMap();
                map.setView([lat, lon], Math.max(map.getZoom(), 16));
                L.popup().setLatLng([lat, lon])
                    .setContent($card.find('.rc-title').text() || 'Record').openOn(map);
            } catch (e) {}
        }
    },

    // ---- station detail mode ---------------------------------------------
    showStationContent: function(opts) {
        opts = opts || {};
        this._mode = 'features';
        $('#ogrid-container').removeClass('results-collapsed').removeClass('viewing-section');
        $('#ogrid-results-panel').removeClass('hide').addClass('station-mode');
        $('#ogrid-sidebar .ogrid-nav-item').removeClass('active').filter('[data-section="search"]').addClass('active');
        $('#ogrid-summarize-wrapper').addClass('hide').removeClass('expanded');
        $('#ogrid-trend-card').empty();
        $('#ogrid-results-count').html(opts.title ? this._esc(opts.title) : 'Details');
        $('#ogrid-results-list').html('<div class="ogrid-station-detail">' + (opts.html || '') + '</div>');
    },

    // ---- map point → highlight its card (feature mode) -------------------
    _onFeatureSelected: function(evt) {
        var msg = evt.message || {};
        if (msg.resultSetId == null || msg.featureId == null) return;
        $('#ogrid-container').removeClass('results-collapsed').removeClass('viewing-section');
        $('#ogrid-results-panel').removeClass('hide');
        var $cards = $('#ogrid-results-list .ogrid-result-card');
        var $match = $cards.filter(function() {
            return String($(this).attr('data-oid')) === String(msg.featureId);
        });
        if (!$match.length) return;
        $match.addClass('expanded');
        var el = $match.get(0);
        if (el && el.scrollIntoView) { el.scrollIntoView({ block: 'nearest' }); }
        $cards.removeClass('rc-flash');
        void el.offsetWidth;
        $match.addClass('rc-flash');
    }
});

ogrid.resultsPanel = function(options) { return new ogrid.ResultsPanel(options); };

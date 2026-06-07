/*
 * ogrid.MapMode
 *
 * Scale-aware, viewport-aware map representation (issue #6). After a search and
 * on every (debounced) pan/zoom, it asks the server (/map/view) what to draw for
 * the current viewport + count:
 *   count ≤ 500           → individual points
 *   > 500, zoomed out     → community-area choropleth
 *   > 500, has tract data → census-tract choropleth
 *   else                  → heatmap
 * The results panel keeps listing the records independently.
 *
 * Points are rendered through the normal pipeline (REFRESH_DATA tagged
 * mapModeSwap so the panel/this controller ignore it); choropleth + heatmap are
 * overlay layers this controller owns.
 */
ogrid.MapMode = ogrid.Class.extend({

    _options: {},

    init: function(options) {
        if (options) { this._options = $.extend(this._options, options); }
        var me = this;

        this._mode = 'points';       // 'points' | 'choropleth' | 'heatmap'
        this._overlay = null;        // owned choropleth/heat layer
        this._eligible = false;
        this._context = null;
        this._primaryCount = 0;
        this._seq = 0;
        this._debounce = null;

        ogrid.Event.on(ogrid.Event.types.REFRESH_DATA, $.proxy(this._onRefresh, this));
        ogrid.Event.on(ogrid.Event.types.CLEAR, $.proxy(this._onClear, this));

        try {
            this._leaflet().on('moveend', function() { me._schedule(); });
        } catch (e) {}
    },

    _leaflet: function() { return this._options.map.getMap(); },

    _onClear: function() {
        this._clearOverlay();
        this._mode = 'points';
        this._eligible = false;
        this._context = null;
        this._primaryCount = 0;
    },

    _onRefresh: function(evt) {
        var msg = evt.message || {};
        var data = msg.data;
        if (!data) return;
        var opts = msg.options || {};
        if (opts.passthroughData && opts.passthroughData.mapModeSwap) return;  // our own render

        if (opts.clear) {
            this._clearOverlay();
            this._mode = 'points';
            this._eligible = false;
            this._context = null;
            this._primaryCount = 0;
        }

        var filters = data.meta && data.meta.filters;
        if (!filters) return;                 // boundary / proximity / MCP / POI

        this._primaryCount++;
        if (this._primaryCount === 1 && filters.dataset_id) {
            this._eligible = true;
            this._context = {
                dataset: filters.dataset_id,
                timeframe: filters.timeframe || 'all',
                community_area: filters.community_area ? filters.community_area.number : null,
                soql_where: filters.soql_where || null
            };
        } else {
            this._eligible = false;           // multi-dataset → no aggregation
            this._context = null;
        }
        this._schedule();
    },

    _schedule: function() {
        var me = this;
        if (!this._eligible) return;
        clearTimeout(this._debounce);
        this._debounce = setTimeout(function() { me._refresh(); }, 400);
    },

    _refresh: function() {
        var me = this;
        if (!this._eligible || !this._context) return;
        var map = this._leaflet();
        var b;
        try { b = map.getBounds(); } catch (e) { return; }
        var payload = $.extend({}, this._context, {
            bbox: { minLat: b.getSouth(), minLon: b.getWest(), maxLat: b.getNorth(), maxLon: b.getEast() },
            zoom: map.getZoom()
        });

        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/map/view';
        var token = (typeof sessionStorage !== 'undefined') ? sessionStorage.getItem('auth_token') : null;
        var seq = ++this._seq;

        $.ajax({
            url: url, type: 'POST', contentType: 'application/json',
            data: JSON.stringify(payload),
            headers: token ? { 'X-AUTH-TOKEN': token } : {},
            timeout: 30000
        }).done(function(res) {
            if (seq !== me._seq) return;       // a newer request superseded this one
            me._apply(res);
        });
    },

    _apply: function(res) {
        if (!res || !res.mode) return;
        if (res.mode === 'points') {
            // Only re-render points if we're coming back from an overlay; otherwise
            // the search's points are already correct.
            if (this._overlay && res.data) { this._renderPoints(res.data); }
            this._clearOverlay();
            this._mode = 'points';
        } else if (res.mode === 'choropleth' && res.data) {
            this._renderOverlay(this._buildChoropleth(res.data));
            this._mode = 'choropleth';
        } else if (res.mode === 'heatmap' && res.points) {
            this._renderOverlay(L.heatLayer(res.points, { radius: 25, blur: 15 }));
            this._mode = 'heatmap';
        }
    },

    _renderPoints: function(fc) {
        // Render through the normal pipeline; flag so the panel/this ignore it.
        ogrid.Event.raise(ogrid.Event.types.REFRESH_DATA, {
            resultSetId: ogrid.guid(),
            data: fc,
            options: { clear: true, passthroughData: { mapModeSwap: true } }
        });
    },

    _renderOverlay: function(layer) {
        this._options.map.hideQueryResultLayers();   // remove point markers
        this._clearOverlay();
        this._overlay = layer.addTo(this._leaflet());
    },

    _buildChoropleth: function(fc) {
        var counts = fc.features.map(function(f) { return f.properties.count || 0; });
        var max = Math.max.apply(null, counts.concat([1]));
        var scale = chroma.scale(['#e3f0fb', '#1565C0']).domain([0, max]);
        return L.geoJSON(fc, {
            style: function(feature) {
                return {
                    fillColor: scale(feature.properties.count || 0).hex(),
                    fillOpacity: 0.7, color: '#1565C0', weight: 1, opacity: 0.8
                };
            },
            onEachFeature: function(feature, layer) {
                var p = feature.properties || {};
                layer.bindPopup('<b>' + p.name + '</b><br>' + (p.count || 0) + ' records');
            }
        });
    },

    _clearOverlay: function() {
        if (this._overlay) {
            try { this._leaflet().removeLayer(this._overlay); } catch (e) {}
            this._overlay = null;
        }
    }
});

ogrid.mapMode = function(options) { return new ogrid.MapMode(options); };

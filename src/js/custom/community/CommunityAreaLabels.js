/*
 * ogrid.CommunityAreaLabels
 *
 * Clickable Chicago community-area NAME labels on the map. Only the name text is
 * clickable (there is no clickable polygon) — clicking a name opens that area's
 * Community Trends profile. Labels scale with zoom (smaller zoomed out, larger zoomed
 * in), mirroring the CTA/Metra station marker behavior, and are suppressed below a
 * minimum zoom where 77 names would overlap into noise.
 *
 * Shown by default; the map toggle button hides/shows them.
 *
 * Backend: GET /geography/community-areas/boundaries (GeoJSON FeatureCollection).
 */
ogrid.CommunityAreaLabels = ogrid.Class.extend({

    // Below this zoom the whole city is a clump — labels would overlap, so hide them.
    _MIN_ZOOM: 11,

    _map: null,
    _group: null,
    _labels: null,      // [{ marker, center, name, number }]
    _loaded: false,
    _enabled: false,    // whether labels are active
    _onMap: false,      // whether the group is currently added to the map

    init: function(options) {
        this._options = options || {};
        this._map = this._options.map;
        this._labels = [];
        this._map.on('zoomend', $.proxy(this._onZoom, this));
        // Community-area names are always on (zoom-gated); no toggle control.
        this.show();
    },

    _endpoint: function() {
        return (this._options.endpoint || ogrid.Config.service.endpoint).replace(/\/$/, '');
    },

    _authHeaders: function() {
        var token = (typeof sessionStorage !== 'undefined') ? sessionStorage.getItem('auth_token') : null;
        return token ? { 'X-AUTH-TOKEN': token } : {};
    },

    // --- zoom-responsive font sizing ---------------------------------------
    _fontForZoom: function(zoom) {
        if (zoom >= 16) return 19;
        if (zoom >= 15) return 17;
        if (zoom >= 14) return 15;
        if (zoom >= 13) return 13;
        if (zoom >= 12) return 11;
        return 10; // zoom 11 (labels are hidden below _MIN_ZOOM)
    },

    _labelIcon: function(name, zoom) {
        return L.divIcon({
            className: 'ocp-map-label',
            html: '<span class="ocp-label-text" style="font-size:' +
                  this._fontForZoom(zoom) + 'px;">' + name + '</span>',
            iconSize: null
        });
    },

    show: function() {
        var me = this;
        this._enabled = true;
        this._ensureLoaded(function() { me._updateVisibility(); });
    },

    hide: function() {
        this._enabled = false;
        if (this._group && this._onMap) { this._map.removeLayer(this._group); }
        this._onMap = false;
    },

    _onZoom: function() {
        if (this._enabled) { this._updateVisibility(); }
    },

    // Add/remove the label group based on zoom, and rescale visible labels.
    _updateVisibility: function() {
        if (!this._group) { return; }
        var zoom = this._map.getZoom();

        if (zoom < this._MIN_ZOOM) {
            if (this._onMap) { this._map.removeLayer(this._group); this._onMap = false; }
            return;
        }
        if (!this._onMap) { this._group.addTo(this._map); this._onMap = true; }
        this._resizeLabels(zoom);
    },

    _resizeLabels: function(zoom) {
        var me = this;
        this._labels.forEach(function(l) {
            l.marker.setIcon(me._labelIcon(l.name, zoom));
        });
    },

    _ensureLoaded: function(cb) {
        if (this._loaded) { cb(); return; }
        var me = this;
        $.ajax({
            url: this._endpoint() + '/geography/community-areas/boundaries',
            type: 'GET',
            headers: this._authHeaders(),
            success: function(fc) {
                me._build(fc);
                me._loaded = true;
                cb();
            },
            error: function() {
                if (ogrid.Alert && ogrid.Alert.error) {
                    ogrid.Alert.error('Could not load community-area names.');
                }
            }
        });
    },

    _open: function(number) {
        // Switch through the app router so browser history captures the profile.
        if (ogrid.App && ogrid.App.navigateToPage) {
            ogrid.App.navigateToPage('trends', { communityArea: number });
        } else {
            ogrid.communityProfile().show();
            ogrid.communityProfile().load(number);
        }
    },

    _build: function(fc) {
        var me = this;
        this._group = L.layerGroup();
        this._labels = [];
        var zoom = this._map.getZoom();

        (fc && fc.features ? fc.features : []).forEach(function(feature) {
            var number = feature.properties.number;
            var name = feature.properties.name;

            // Centroid via an in-memory GeoJSON layer (never added to the map);
            // we only render the clickable name, not the polygon.
            var center;
            try {
                center = L.geoJSON(feature).getBounds().getCenter();
            } catch (e) {
                return; // skip degenerate geometry
            }

            var marker = L.marker(center, {
                interactive: true,
                keyboard: false,
                icon: me._labelIcon(name, zoom),
                zIndexOffset: 650
            });
            marker.on('click', function() { me._open(number); });
            me._group.addLayer(marker);
            me._labels.push({ marker: marker, center: center, name: name, number: number });
        });
    }
});

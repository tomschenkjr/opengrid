/*
 * Google Street View popup helper.
 *
 * Keeps Street View image construction in one place for query-result features
 * and persistent object markers. The API key is read at render time so
 * environment overrides can provide it after the main bundle loads.
 */
(function() {
    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _cfg() {
        var mapCfg = (ogrid.Config && ogrid.Config.map) || {};
        return mapCfg.googleStreetView || {};
    }

    function _key() {
        var mapCfg = (ogrid.Config && ogrid.Config.map) || {};
        return (mapCfg.googleStreetViewApiKey || ogrid.Config.googleStreetViewApiKey || '').trim();
    }

    function _num(v) {
        var n = parseFloat(v);
        return isNaN(n) ? null : n;
    }

    function _latLon(opts) {
        opts = opts || {};
        var lat = _num(opts.lat != null ? opts.lat : opts.latitude);
        var lon = _num(opts.lon != null ? opts.lon : opts.lng != null ? opts.lng : opts.longitude);
        if (lat == null || lon == null) return null;
        return { lat: lat, lon: lon };
    }

    function _url(lat, lon) {
        var cfg = _cfg();
        var params = [
            'size=' + encodeURIComponent(cfg.size || '320x180'),
            'location=' + encodeURIComponent(lat + ',' + lon),
            'fov=' + encodeURIComponent(cfg.fov || 80),
            'pitch=' + encodeURIComponent(cfg.pitch || 0),
            'radius=' + encodeURIComponent(cfg.radius || 50),
            'source=outdoor',
            'key=' + encodeURIComponent(_key())
        ];
        return 'https://maps.googleapis.com/maps/api/streetview?' + params.join('&');
    }

    function imageHtml(opts) {
        var ll = _latLon(opts);
        if (!ll) return '';

        if (!_key()) {
            return '<div class="ogrid-streetview ogrid-streetview-empty">' +
                   '<i class="fa fa-street-view" aria-hidden="true"></i>' +
                   '<span>Street View needs a Google API key.</span>' +
                   '</div>';
        }

        return '<div class="ogrid-streetview">' +
               '<img src="' + _esc(_url(ll.lat, ll.lon)) + '" alt="Google Street View image" loading="lazy">' +
               '</div>';
    }

    function popupHtml(opts) {
        opts = opts || {};
        var title = opts.title
            ? '<div class="ogrid-streetview-title">' + _esc(opts.title) + '</div>'
            : '';
        var body = opts.body || '';
        return '<div class="ogrid-streetview-popup">' +
               title +
               imageHtml(opts) +
               body +
               '</div>';
    }

    function attachToMarker(marker, opts) {
        if (!marker || !marker.bindPopup) return marker;
        marker.bindPopup('', { maxWidth: 360, className: 'ogrid-streetview-leaflet-popup' });
        marker.on('popupopen', function() {
            marker.setPopupContent(popupHtml(opts || {}));
        });
        return marker;
    }

    function openMarkerPopup(marker) {
        if (marker && marker.openPopup) {
            marker.openPopup();
        }
    }

    ogrid.StreetView = {
        attachToMarker: attachToMarker,
        imageHtml: imageHtml,
        openMarkerPopup: openMarkerPopup,
        popupHtml: popupHtml
    };
}());

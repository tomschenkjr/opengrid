/*
 * Beach Lab DNA water-quality stations — persistent map markers.
 *
 * One marker per Chicago beach at its sample location, showing the most recent
 * DNA reading (source: data.cityofchicago.org/resource/hmqm-anjq, served via
 * GET /stations/beach-dna). Markers appear only when zoomed in a few steps
 * past the Dever Crib threshold (zoom 14) — see MIN_ZOOM below.
 */
(function() {
    var MIN_ZOOM = 15; 

    // Marker icon + green label styles
    var s = document.createElement('style');
    s.textContent = [
        '.ogrid-beach-marker{background:transparent;border:none;}',
        '.ogrid-beach-icon-wrap{width:26px;height:26px;background:#2e7d32;border:2px solid #ecf0f1;',
        '  border-radius:50%;display:flex;align-items:center;justify-content:center;',
        '  cursor:pointer;box-shadow:0 2px 5px rgba(0,0,0,0.5);}',
        '.ogrid-beach-icon-wrap .fa{color:#ecf0f1;font-size:12px;line-height:1;}',
        '.ogrid-beach-label.leaflet-tooltip{background:transparent!important;border:none!important;',
        '  box-shadow:none!important;color:#2e7d32!important;font-size:11px!important;',
        '  font-weight:bold!important;padding:3px 8px!important;white-space:nowrap!important;',
        '  text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,',
        '    -2px 0 0 #fff,2px 0 0 #fff,0 -2px 0 #fff,0 2px 0 #fff,0 2px 6px rgba(0,0,0,0.5)!important;}',
        '.ogrid-beach-label.leaflet-tooltip::before{display:none!important;}'
    ].join('');
    document.head.appendChild(s);

    var _icon = L.divIcon({
        className: 'ogrid-beach-marker',
        html: '<div class="ogrid-beach-icon-wrap"><i class="fa fa-tint"></i></div>',
        iconSize: [26, 26],
        iconAnchor: [13, 13],
        popupAnchor: [0, -16]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _fmtTime(ts) {
        if (!ts) return '';
        try { return moment(ts).format('MMM D, YYYY h:mm A'); }
        catch (e) { return String(ts).substring(0, 10); }
    }

    function _popupHtml(b) {
        return '<b>' + _esc(b.beach) + '</b><br>' +
               '<b>DNA Reading Mean:</b> ' + _esc(b.dna_reading_mean) + '<br>' +
               '<span style="font-size:0.82em;opacity:0.7;">' + _esc(_fmtTime(b.timestamp)) + '</span>';
    }

    function _addBeach(b, map, state) {
        var marker = L.marker([b.latitude, b.longitude], {icon: _icon, zIndexOffset: 900})
            .bindTooltip(b.beach + ' Water Quality Tests', {
                permanent: true, direction: 'right',
                className: 'ogrid-beach-label', offset: [4, 0]
            });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: b.latitude,
                lon: b.longitude,
                title: b.beach + ' Water Quality Tests'
            });
        }
        marker.on('click', function() {
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
                ogrid.App._rp.showStationContent({ title: b.beach + ' Water Quality Tests', html: _popupHtml(b) });
            }
        });
        state.markers.push(marker);
    }

    function _updateVisibility(map, state) {
        var show = map.getZoom() >= MIN_ZOOM;
        if (show && !state.onMap) {
            state.markers.forEach(function(m) { m.addTo(map); });
            state.onMap = true;
        } else if (!show && state.onMap) {
            state.markers.forEach(function(m) { m.remove(); });
            state.onMap = false;
        }
    }

    function init(map) {
        var state = { markers: [], onMap: false };
        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/stations/beach-dna';

        $.ajax({ url: url, type: 'GET', timeout: 15000 })
            .done(function(list) {
                (list || []).forEach(function(b) { _addBeach(b, map, state); });
                map.on('zoomend', function() { _updateVisibility(map, state); });
                _updateVisibility(map, state);
            });
    }

    // Wait for the Leaflet map, then load the beach stations
    var attempts = 0;
    var poll = setInterval(function() {
        attempts++;
        try {
            var map = ogrid.App.map().getMap();
            if (map) { clearInterval(poll); init(map); }
        } catch (e) {}
        if (attempts >= 30) clearInterval(poll);
    }, 500);
}());

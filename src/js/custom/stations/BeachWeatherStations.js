/*
 * Beach weather stations — persistent map markers.
 *
 * Merges sensor LOCATIONS (g3ip-u8rb) with the latest MEASUREMENT per station
 * (k7hf-8y75), served pre-joined via GET /stations/beach-weather. One wave
 * marker per station; appears at zoom >= 16. Popup shows the most recent reading.
 */
(function() {
    var MIN_ZOOM = 15;

    var s = document.createElement('style');
    s.textContent = [
        '.ogrid-bweather-marker{background:transparent;border:none;}',
        '.ogrid-bweather-icon-wrap{width:26px;height:26px;background:#1565C0;border:2px solid #ecf0f1;',
        '  border-radius:50%;display:flex;align-items:center;justify-content:center;',
        '  cursor:pointer;box-shadow:0 2px 5px rgba(0,0,0,0.5);}',
        '.ogrid-bweather-label.leaflet-tooltip{background:transparent!important;border:none!important;',
        '  box-shadow:none!important;color:#1565C0!important;font-size:11px!important;',
        '  font-weight:bold!important;padding:3px 8px!important;white-space:nowrap!important;',
        '  text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,',
        '    -2px 0 0 #fff,2px 0 0 #fff,0 -2px 0 #fff,0 2px 0 #fff,0 2px 6px rgba(0,0,0,0.5)!important;}',
        '.ogrid-bweather-label.leaflet-tooltip::before{display:none!important;}'
    ].join('');
    document.head.appendChild(s);

    var _wave = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">' +
        '<path d="M1 14c2.5-4 5-4 7.5 0s5 4 7.5 0 5-4 7.5 0" fill="none" ' +
        'stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>';

    var _icon = L.divIcon({
        className: 'ogrid-bweather-marker',
        html: '<div class="ogrid-bweather-icon-wrap">' + _wave + '</div>',
        iconSize: [26, 26],
        iconAnchor: [13, 13],
        popupAnchor: [0, -16]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // "Foster Weather Station" → label "Foster Weather Station" (strip + re-add
    // the suffix so we never produce "... Weather Station Weather Station")
    function _label(name) {
        var beach = String(name || '').replace(/\s*Weather Station\s*$/i, '');
        return (beach || name) + ' Weather Station';
    }

    function _row(label, value, unit) {
        if (value == null || value === '') return '';
        return '<b>' + label + ':</b> ' + _esc(value) + (unit || '') + '<br>';
    }

    // Celsius → Fahrenheit (rounded); returns null for blank/non-numeric input
    function _toF(c) {
        if (c == null || c === '') return null;
        var n = parseFloat(c);
        return isNaN(n) ? null : Math.round(n * 9 / 5 + 32);
    }

    // m/s → mph (1 decimal); returns null for blank/non-numeric input
    function _toMph(ms) {
        if (ms == null || ms === '') return null;
        var n = parseFloat(ms);
        return isNaN(n) ? null : Math.round(n * 2.23694 * 10) / 10;
    }

    function _when(m) {
        return m.measurement_timestamp_label || m.measurement_timestamp || '';
    }

    // Compact history table under the most recent reading
    function _historyHtml(history) {
        if (!history || !history.length) return '';
        var rows = history.map(function(h) {
            var f = _toF(h.air_temperature);
            var mph = _toMph(h.wind_speed);
            return '<tr><td>' + _esc(_when(h)) + '</td>' +
                   '<td>' + (f == null ? '—' : f + '°F') + '</td>' +
                   '<td>' + (h.humidity ? _esc(h.humidity) + '%' : '—') + '</td>' +
                   '<td>' + (mph == null ? '—' : mph + ' mph') + '</td></tr>';
        }).join('');
        return '<div class="bw-history"><div class="bw-history-title">Earlier readings</div>' +
               '<table><thead><tr><th>Time</th><th>Temp</th><th>Hum.</th><th>Wind</th></tr></thead>' +
               '<tbody>' + rows + '</tbody></table></div>';
    }

    function _popupHtml(st) {
        var m = st.measurement;
        var head = '<b>' + _esc(_label(st.station_name)) + '</b><br>';
        if (!m) return head + '<span style="opacity:0.6;">No recent reading.</span>';
        var wind = '';
        var mph = _toMph(m.wind_speed);
        if (mph != null) {
            wind = mph + ' mph' + (m.wind_direction ? ' @ ' + m.wind_direction + '°' : '');
        }
        var airF = _toF(m.air_temperature);
        return head +
            '<div class="bw-current">' +
            _row('Air Temp', airF == null ? null : airF, airF == null ? null : '°F') +
            _row('Humidity', m.humidity, '%') +
            _row('Wind', wind || null) +
            _row('Pressure', m.barometric_pressure, ' hPa') +
            _row('Solar', m.solar_radiation, ' W/m²') +
            '<span style="font-size:0.82em;opacity:0.7;">Observed: ' + _esc(_when(m)) + '</span>' +
            '</div>' +
            _historyHtml(st.history);
    }

    function _add(st, state) {
        var marker = L.marker([st.latitude, st.longitude], {icon: _icon, zIndexOffset: 900})
            .bindTooltip(_label(st.station_name), {
                permanent: true, direction: 'right',
                className: 'ogrid-bweather-label', offset: [4, 0]
            });
        marker.on('click', function() {
            if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
                ogrid.App._rp.showStationContent({ title: _label(st.station_name), html: _popupHtml(st) });
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
        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/stations/beach-weather';
        $.ajax({ url: url, type: 'GET', timeout: 15000 })
            .done(function(list) {
                (list || []).forEach(function(st) { _add(st, state); });
                map.on('zoomend', function() { _updateVisibility(map, state); });
                _updateVisibility(map, state);
            });
    }

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

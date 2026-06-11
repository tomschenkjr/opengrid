/*
 * DivvyLayer — persistent Divvy bike station markers, viewport-loaded at zoom 17+.
 *
 * Stations are fetched for the current map bounds from /stations/divvy-stations.
 * Click a station -> show GBFS availability and dock details in the Results Pane.
 */
(function () {
    var DIVVY_BLUE = '#40b4e5';
    var STOPS_ZOOM = 17; // Match CTA bus stop visibility.
    var DIVVY_LOGO_PATHS =
        '<path d="M124.9 17.2c-1.1 0-2.2.5-2.9 1.3l-47 47-47.1-47c-.8-.9-1.8-1.3-2.9-1.3-1.8 0-3.1 1.4-3.1 3.2v14.1c0 1.2.4 2.3 1.3 3.1L67 81.3c1 .9 2.2 1.4 3.5 1.4h8.6c1.3 0 2.5-.5 3.5-1.4l43.8-43.6c.9-.8 1.3-1.9 1.3-3.1v-14c.2-1.8-1.1-3.2-2.7-3.4h-.1" fill="' + DIVVY_BLUE + '"/>' +
        '<path d="M124.9 70.3c-1.1 0-2.2.5-2.9 1.3l-47 47-47-47c-.8-.9-1.8-1.3-2.9-1.3-1.8 0-3.1 1.4-3.1 3.2v14.1c0 1.2.4 2.3 1.3 3.1l43.8 43.6c1 .9 2.2 1.4 3.5 1.4h8.6c1.3 0 2.5-.5 3.5-1.4l43.8-43.7c.9-.8 1.3-1.9 1.3-3.1V73.7c.1-1.8-1.1-3.2-2.7-3.4h-.2" fill="' + DIVVY_BLUE + '"/>';
    var DIVVY_MARKER_SVG =
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">' +
        '<rect x="1" y="1" width="18" height="18" rx="5" fill="#fff" stroke="' + DIVVY_BLUE + '" stroke-width="2"/>' +
        '<svg x="4" y="4" width="12" height="12" viewBox="0 0 150 150">' +
        DIVVY_LOGO_PATHS +
        '</svg>' +
        '</svg>';

    var _DIVVY_ICON = L.icon({
        className: 'ogrid-divvy-marker',
        iconUrl: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(DIVVY_MARKER_SVG),
        iconSize: [20, 20],
        iconAnchor: [10, 10],
        popupAnchor: [0, -11]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _fmtNum(value) {
        return value == null || value === '' ? 'n/a' : _esc(value);
    }

    function _vehicleCounts(types) {
        var parts = [];
        (types || []).forEach(function(type) {
            parts.push(_esc(type.count || 0) + ' ' + _esc(type.label || type.vehicle_type_id || 'vehicles'));
        });
        return parts.length ? parts.join(', ') : 'n/a';
    }

    function _availabilityPill(types) {
        var available = [];
        (types || []).forEach(function(type) {
            var count = Number(type.count || 0);
            if (count > 0) {
                available.push(_esc(count) + ' ' + _esc(type.label || type.vehicle_type_id || 'vehicles'));
            }
        });
        if (!available.length) {
            return 'No vehicles<br>available';
        }
        return available.join('<br>') + '<br>available';
    }

    function _detailCard(station) {
        var available = station.vehicle_types_available_count || 0;
        var color = available > 0 ? DIVVY_BLUE : '#7d8a96';
        var pill = _availabilityPill(station.vehicle_types_available);
        var sub = 'Available vehicles: ' + _vehicleCounts(station.vehicle_types_available) +
                  ' &middot; Disabled vehicles: ' + _fmtNum(station.num_vehicles_disabled) +
                  ' &middot; Docks available: ' + _fmtNum(station.num_docks_available);
        return '<div class="ogrid-result-card ogrid-divvy-result-card expanded" style="border-left-color:' + color + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(station.name || 'Divvy Station') + '</div>' +
               '</div>' +
               '<div class="ogrid-divvy-pill-row"><span class="rc-pill ogrid-divvy-pill">' + pill + '</span></div>' +
               '<div class="rc-sub">' + sub + '</div>' +
               '</div>';
    }

    function _showStation(station) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: 'Divvy Station',
                html: _detailCard(station)
            });
        }
    }

    function _buildMarker(station) {
        var marker = L.marker([station.lat, station.lon], { icon: _DIVVY_ICON, zIndexOffset: 220 });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: station.lat,
                lon: station.lon,
                title: station.name || 'Divvy Station'
            });
        }
        marker.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            _showStation(station);
        });
        return marker;
    }

    function _loadForBounds(bounds, state, base) {
        state.markerGroup.clearLayers();
        $.ajax({
            url: base + '/stations/divvy-stations',
            data: {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: 15000
        }).done(function(stations) {
            (stations || []).forEach(function(station) {
                _buildMarker(station).addTo(state.markerGroup);
            });
        });
    }

    function _update(map, state, base) {
        var zoom = map.getZoom();
        if (zoom >= STOPS_ZOOM) {
            if (!state.onMap) {
                state.markerGroup.addTo(map);
                state.onMap = true;
            }
            _loadForBounds(map.getBounds(), state, base);
        } else if (state.onMap) {
            state.markerGroup.remove();
            state.markerGroup.clearLayers();
            state.onMap = false;
        }
    }

    function init(map) {
        var state = { markerGroup: L.layerGroup(), onMap: false };
        var base = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';

        map.on('moveend', function() { _update(map, state, base); });
        map.on('zoomend', function() { _update(map, state, base); });
        _update(map, state, base);
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

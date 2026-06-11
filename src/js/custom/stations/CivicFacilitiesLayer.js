/*
 * CivicFacilitiesLayer — persistent public facility markers.
 *
 * Libraries, police stations, fire stations, and speed cameras appear with CPS
 * schools at zoom 16+. Bike racks appear one step closer at zoom 17+.
 */
(function () {
    var SCHOOL_ZOOM = 16;
    var AFTER_BUS_STOP_ZOOM = 18;

    var TYPES = [
        {
            id: 'libraries',
            label: 'Library',
            zoom: SCHOOL_ZOOM,
            color: '#0f766e',
            icon: 'fa-book',
            z: 185
        },
        {
            id: 'police-stations',
            label: 'Police Station',
            zoom: SCHOOL_ZOOM,
            color: '#1d4ed8',
            icon: 'fa-shield',
            z: 186
        },
        {
            id: 'fire-stations',
            label: 'Fire Station',
            zoom: SCHOOL_ZOOM,
            color: '#dc2626',
            icon: 'fa-fire',
            z: 187
        },
        {
            id: 'speed-cameras',
            label: 'Speed Camera',
            zoom: AFTER_BUS_STOP_ZOOM,
            color: '#b45309',
            icon: 'fa-camera',
            z: 188
        },
        {
            id: 'bike-racks',
            label: 'Bike Rack',
            zoom: AFTER_BUS_STOP_ZOOM,
            color: '#16a34a',
            icon: 'fa-bicycle',
            z: 189
        }
    ];

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _type(typeId) {
        return TYPES.filter(function(t) { return t.id === typeId; })[0] || TYPES[0];
    }

    function _icon(type) {
        return L.divIcon({
            className: 'ogrid-facility-marker ogrid-facility-' + type.id,
            html: '<div class="ogrid-facility-icon-wrap" style="background:' + type.color + '">' +
                  '<i class="fa ' + type.icon + '"></i>' +
                  '</div>',
            iconSize: [18, 18],
            iconAnchor: [9, 9],
            popupAnchor: [0, -11]
        });
    }

    function _row(label, value) {
        if (value == null || value === '') {
            return '';
        }
        return '<div class="rc-row"><span class="rc-k">' + _esc(label) + '</span>' +
               '<span class="rc-v">' + _esc(value) + '</span></div>';
    }

    function _details(details) {
        return (details || []).map(function(d) {
            return _row(d.label, d.value);
        }).join('');
    }

    function _detailCard(item) {
        var type = _type(item.kind);
        var rows = _details(item.details);
        return '<div class="ogrid-result-card ogrid-facility-result-card expanded" style="border-left-color:' + type.color + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(item.title || type.label) + '</div>' +
               '<div class="rc-top-right"><span class="rc-pill ogrid-facility-pill" style="color:' + type.color + ';border-color:' + type.color + '">' +
               _esc(item.pill || type.label) + '</span></div>' +
               '</div>' +
               (item.subtitle ? '<div class="rc-sub">' + _esc(item.subtitle) + '</div>' : '') +
               '<div class="rc-details">' + (rows || '<div class="rc-row">No details available.</div>') + '</div>' +
               '</div>';
    }

    function _showFacility(item) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: item.kind_label || _type(item.kind).label,
                html: _detailCard(item)
            });
        }
    }

    function _buildMarker(item) {
        var type = _type(item.kind);
        var marker = L.marker([item.lat, item.lon], {
            icon: _icon(type),
            zIndexOffset: type.z
        });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: item.lat,
                lon: item.lon,
                title: item.title || type.label
            });
        }
        marker.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            _showFacility(item);
        });
        return marker;
    }

    function _loadType(type, bounds, state, base) {
        state.groups[type.id].clearLayers();
        $.ajax({
            url: base + '/stations/facilities/' + type.id,
            data: {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: type.id === 'bike-racks' ? 25000 : 15000
        }).done(function(items) {
            (items || []).forEach(function(item) {
                _buildMarker(item).addTo(state.groups[type.id]);
            });
        });
    }

    function _updateType(map, state, base, type) {
        var group = state.groups[type.id];
        if (map.getZoom() >= type.zoom) {
            if (!state.onMap[type.id]) {
                group.addTo(map);
                state.onMap[type.id] = true;
            }
            _loadType(type, map.getBounds(), state, base);
        } else if (state.onMap[type.id]) {
            group.remove();
            group.clearLayers();
            state.onMap[type.id] = false;
        }
    }

    function _update(map, state, base) {
        TYPES.forEach(function(type) {
            _updateType(map, state, base, type);
        });
    }

    function _injectStyles() {
        if (document.getElementById('ogrid-facility-layer-style')) {
            return;
        }
        var s = document.createElement('style');
        s.id = 'ogrid-facility-layer-style';
        s.textContent =
            '.ogrid-facility-marker{background:transparent;border:none;}' +
            '.ogrid-facility-icon-wrap{width:18px;height:18px;border:2px solid #ecf0f1;' +
            'border-radius:50%;display:flex;align-items:center;justify-content:center;' +
            'cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,0.4);}' +
            '.ogrid-facility-icon-wrap .fa{color:#ecf0f1;font-size:8px;line-height:1;}' +
            '.ogrid-result-card.ogrid-facility-result-card{cursor:default;}' +
            '.ogrid-facility-pill{white-space:normal;text-align:left;}';
        document.head.appendChild(s);
    }

    function init(map) {
        _injectStyles();
        var state = { groups: {}, onMap: {} };
        TYPES.forEach(function(type) {
            state.groups[type.id] = L.layerGroup();
            state.onMap[type.id] = false;
        });
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

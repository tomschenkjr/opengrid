/*
 * ParkLayer — persistent Chicago Park District park boundary polygons.
 *
 * Parks render as invisible hit areas in a low z-index pane so event and
 * persistent-object point markers remain above them. Clicking a park highlights
 * its boundary and opens details in the Results Pane.
 */
(function () {
    var PARK_GREEN = '#2f8f46';
    var PARK_FILL = '#8fd19e';

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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

    function _feature(item) {
        return {
            type: 'Feature',
            id: item.id,
            geometry: item.geometry,
            properties: item
        };
    }

    function _card(item) {
        var rows = _details(item.details);
        return '<div class="ogrid-result-card ogrid-park-result-card expanded" style="border-left-color:' + PARK_GREEN + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(item.title || item.park || 'Chicago Park') + '</div>' +
               '<div class="rc-top-right"><span class="rc-pill ogrid-park-pill">' + _esc(item.pill || 'Park') + '</span></div>' +
               '</div>' +
               (item.subtitle ? '<div class="rc-sub">' + _esc(item.subtitle) + '</div>' : '') +
               '<div class="rc-details">' + (rows || '<div class="rc-row">No park details available.</div>') + '</div>' +
               '</div>';
    }

    function _showPark(item) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: 'Park',
                html: _card(item)
            });
        }
    }

    function _style(feature) {
        return {
            pane: 'ogrid-parks-pane',
            color: 'transparent',
            weight: 2,
            opacity: 0,
            fill: true,
            fillColor: 'transparent',
            fillOpacity: 0
        };
    }

    function _highlightStyle(layer) {
        layer.setStyle({
            color: PARK_GREEN,
            weight: 3,
            opacity: 1,
            fillColor: PARK_FILL,
            fillOpacity: 0.24
        });
    }

    function _resetLayer(state, layer) {
        if (state.layer) {
            state.layer.resetStyle(layer);
        }
    }

    function _clearSelection(state) {
        if (state.selectedLayer) {
            _resetLayer(state, state.selectedLayer);
        }
        state.selectedId = null;
        state.selectedLayer = null;
    }

    function _selectLayer(state, feature, layer) {
        if (state.selectedLayer === layer) {
            _clearSelection(state);
            return false;
        }
        if (state.selectedLayer && state.selectedLayer !== layer) {
            _resetLayer(state, state.selectedLayer);
        }
        state.selectedId = feature.id || (feature.properties || {}).id;
        state.selectedLayer = layer;
        _highlightStyle(layer);
        if (layer.bringToFront) {
            layer.bringToFront();
        }
        return true;
    }

    function _suppressMapClick(state) {
        state.ignoreNextMapClick = true;
        setTimeout(function() {
            state.ignoreNextMapClick = false;
        }, 0);
    }

    function _onEachFeature(feature, layer, state) {
        var item = feature.properties || {};
        layer.on({
            click: function(e) {
                _suppressMapClick(state);
                if (e && e.originalEvent) {
                    L.DomEvent.stop(e.originalEvent);
                }
                if (_selectLayer(state, feature, layer)) {
                    _showPark(item);
                }
            }
        });
        if (state.selectedId && state.selectedId === (feature.id || item.id)) {
            state.selectedLayer = layer;
            _highlightStyle(layer);
        }
        if (item.title || item.park) {
            layer.bindTooltip(_esc(item.title || item.park), {
                sticky: true,
                className: 'ogrid-park-tooltip'
            });
        }
    }

    function _injectStyles() {
        if (document.getElementById('ogrid-park-layer-style')) {
            return;
        }
        var s = document.createElement('style');
        s.id = 'ogrid-park-layer-style';
        s.textContent =
            '.ogrid-park-tooltip.leaflet-tooltip{background:#fff;border:1px solid rgba(47,143,70,.35);' +
            'box-shadow:0 2px 8px rgba(0,0,0,.15);color:#1f5f30;font-size:11px;font-weight:700;}' +
            '.ogrid-result-card.ogrid-park-result-card{cursor:default;}' +
            '.ogrid-park-pill{color:' + PARK_GREEN + ';border-color:' + PARK_GREEN + ';white-space:normal;text-align:left;}';
        document.head.appendChild(s);
    }

    function _ensurePane(map) {
        if (!map.getPane || !map.createPane) {
            return;
        }
        var pane = map.getPane('ogrid-parks-pane') || map.createPane('ogrid-parks-pane');
        pane.style.zIndex = 350;
        pane.style.pointerEvents = 'auto';
    }

    function _load(map, state, base) {
        var bounds = map.getBounds();
        var seq = ++state.seq;
        $.ajax({
            url: base + '/stations/parks',
            data: {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: 25000
        }).done(function(parks) {
            if (seq !== state.seq) {
                return;
            }
            var features = (parks || []).filter(function(p) {
                return p && p.geometry;
            }).map(_feature);
            if (state.layer) {
                state.selectedLayer = null;
                state.layer.clearLayers();
                state.layer.addData({ type: 'FeatureCollection', features: features });
                return;
            }
            state.layer = L.geoJson({ type: 'FeatureCollection', features: features }, {
                pane: 'ogrid-parks-pane',
                bubblingMouseEvents: false,
                style: _style,
                onEachFeature: function(feature, layer) {
                    _onEachFeature(feature, layer, state);
                }
            }).addTo(map);
        });
    }

    function init(map) {
        _injectStyles();
        _ensurePane(map);
        var state = {
            layer: null,
            seq: 0,
            selectedId: null,
            selectedLayer: null,
            ignoreNextMapClick: false
        };
        var base = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';

        map.on('moveend', function() { _load(map, state, base); });
        map.on('zoomend', function() { _load(map, state, base); });
        map.on('click', function() {
            if (state.ignoreNextMapClick) {
                state.ignoreNextMapClick = false;
                return;
            }
            _clearSelection(state);
        });
        _load(map, state, base);
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

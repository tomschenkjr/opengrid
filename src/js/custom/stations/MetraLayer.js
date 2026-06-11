/*
 * MetraLayer — persistent Metra commuter rail stations and lines.
 *
 * Lines:     visible zoom 9+, colored by route from GTFS.
 * Stations:  visible zoom 10+, scaled fa-train marker (dark maroon).
 * Labels:    visible zoom 13+.
 *
 * Click station → scheduled departures as result cards.
 * Click a departure card → highlights that route's line on the map.
 * Clicking the same card again (or a different station) clears the highlight.
 */
(function () {
    var METRA_BLUE = '#004B87';
    var STATIONS_ZOOM = 14;
    var LABELS_ZOOM   = 16;

    // --- icon scaling (same pattern as CTALayer) ----------------------------

    function _iconSpec(zoom) {
        if (zoom >= 16) return { size: 22, border: 2,   fa: true  };
        if (zoom >= 14) return { size: 18, border: 2,   fa: true  };
        if (zoom >= 12) return { size: 14, border: 1.5, fa: true  };
        if (zoom >= 10) return { size: 10, border: 1,   fa: false };
        return                  { size: 8,  border: 1,   fa: false };
    }

    var _iconCache = {};

    function _iconForZoom(zoom) {
        var spec = _iconSpec(zoom);
        var key  = spec.size;
        if (!_iconCache[key]) {
            var s    = spec.size;
            var half = Math.round(s / 2);
            var fa   = Math.round(s * 0.45);
            var inner = spec.fa
                ? '<i class="fa fa-train" style="color:#ecf0f1;font-size:' + fa + 'px;line-height:1;"></i>'
                : '';
            _iconCache[key] = L.divIcon({
                className: 'ogrid-metra-marker',
                html: '<div style="width:' + s + 'px;height:' + s + 'px;' +
                      'background:' + METRA_BLUE + ';border:' + spec.border + 'px solid #ecf0f1;' +
                      'border-radius:3px;display:flex;align-items:center;' +
                      'justify-content:center;cursor:pointer;' +
                      'box-shadow:0 1px 3px rgba(0,0,0,0.45);">' + inner + '</div>',
                iconSize:   [s, s],
                iconAnchor: [half, half]
            });
        }
        return _iconCache[key];
    }

    // --- helpers ------------------------------------------------------------

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // --- departure cards ----------------------------------------------------

    function _pillLabel(dep) {
        if (dep.minutes <= 1) return 'Due';
        return dep.minutes + ' min';
    }

    function _departureCard(dep) {
        var color  = dep.route_color || METRA_BLUE;
        var title  = _esc(dep.route_name + ' → ' + dep.headsign);
        var pill   = '<span class="rc-pill">' + _esc(_pillLabel(dep)) + '</span>';
        var toggle = '<button type="button" class="rc-toggle" aria-label="Toggle details">' +
                     '<i class="fa fa-chevron-down"></i></button>';
        var sub    = _esc(dep.time_str);
        var detail = '<div class="rc-row"><span class="rc-k">Line</span>' +
                     '<span class="rc-v">' + _esc(dep.route_name) + '</span></div>' +
                     '<div class="rc-row"><span class="rc-k">Scheduled</span>' +
                     '<span class="rc-v">' + _esc(dep.time_str) + '</span></div>';
        return '<div class="ogrid-result-card" style="border-left-color:' + color + '" ' +
               'data-metra-route="' + _esc(dep.route_id) + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + title + '</div>' +
               '<div class="rc-top-right">' + pill + toggle + '</div>' +
               '</div>' +
               '<div class="rc-sub">' + sub + '</div>' +
               '<div class="rc-details">' + detail + '</div>' +
               '</div>';
    }

    function _departuresHtml(deps) {
        if (!deps || !deps.length) {
            return '<div class="ogrid-empty">No scheduled departures for the rest of today.</div>';
        }
        return deps.map(function(d) { return _departureCard(d); }).join('');
    }

    function _fetchDepartures(stop, base) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: stop.stop_name,
                html:  '<div class="cta-arrivals-placeholder" ' +
                       'style="margin-top:8px;font-size:12px;opacity:0.6;">Loading departures&hellip;</div>'
            });
        }
        $.ajax({ url: base + '/stations/metra-departures', data: { stop_id: stop.stop_id }, timeout: 20000 })
            .done(function(deps) {
                $('.cta-arrivals-placeholder').replaceWith(_departuresHtml(deps));
            })
            .fail(function() {
                $('.cta-arrivals-placeholder').text('Departures unavailable.');
            });
    }

    // --- line highlighting --------------------------------------------------

    function _highlightRoute(routeId, state, map) {
        if (!state.linesLayer) return;
        state.highlightedRoute = routeId;
        if (!state.linesOnMap) {
            state.linesLayer.addTo(map);
            state.linesOnMap = true;
        }
        state.linesLayer.eachLayer(function(layer) {
            var rid = layer.feature.properties.route_id;
            if (rid === routeId) {
                layer.setStyle({ weight: 5, opacity: 1.0 });
                layer.bringToFront();
            } else {
                layer.setStyle({ weight: 2, opacity: 0.2 });
            }
        });
    }

    function _clearLineHighlight(state) {
        if (!state.linesLayer) return;
        if (state.linesOnMap) {
            state.linesLayer.remove();
            state.linesOnMap = false;
        }
        state.highlightedRoute = null;
    }

    // --- markers ------------------------------------------------------------

    function _buildMarker(stop, state, zoom, base) {
        var m = L.marker([stop.lat, stop.lon], { icon: _iconForZoom(zoom), zIndexOffset: 400 });
        m._metraStopName = stop.stop_name;
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(m, {
                lat: stop.lat,
                lon: stop.lon,
                title: stop.stop_name
            });
        }
        m.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(m);
            }
            _clearLineHighlight(state);
            state.selectedStation = m;
            _fetchDepartures(stop, base);
        });
        return m;
    }

    // --- zoom visibility + resizing -----------------------------------------

    function _syncLabels(markers, zoom) {
        var show = zoom >= LABELS_ZOOM;
        markers.forEach(function(m) {
            if (show && !m.getTooltip()) {
                m.bindTooltip(m._metraStopName || '', {
                    permanent: true, direction: 'right',
                    className: 'ogrid-metra-label', offset: [6, 0]
                });
            } else if (!show && m.getTooltip()) {
                m.unbindTooltip();
            }
        });
    }

    function _resizeMarkers(markers, zoom) {
        var icon = _iconForZoom(zoom);
        markers.forEach(function(m) { m.setIcon(icon); });
    }

    function _updateVisibility(map, state) {
        var zoom = map.getZoom();

        // Lines are only shown on card click — never auto-displayed by zoom

        if (zoom >= STATIONS_ZOOM && !state.markersOnMap) {
            state.markerGroup.addTo(map); state.markersOnMap = true;
        } else if (zoom < STATIONS_ZOOM && state.markersOnMap) {
            state.markerGroup.remove(); state.markersOnMap = false;
        }

        if (state.markersOnMap && state.markers.length) {
            _resizeMarkers(state.markers, zoom);
            _syncLabels(state.markers, zoom);
        }
    }

    // --- styles -------------------------------------------------------------

    function _injectStyles() {
        var s = document.createElement('style');
        s.textContent =
            '.ogrid-metra-marker{background:transparent;border:none;}' +
            '.ogrid-metra-label.leaflet-tooltip{background:transparent!important;border:none!important;' +
            '  box-shadow:none!important;color:' + METRA_BLUE + '!important;font-size:11px!important;' +
            '  font-weight:bold!important;padding:2px 5px!important;white-space:nowrap!important;' +
            '  text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,' +
            '    0 0 5px rgba(255,255,255,0.9)!important;}' +
            '.ogrid-metra-label.leaflet-tooltip::before{display:none!important;}';
        document.head.appendChild(s);
    }

    // --- init ---------------------------------------------------------------

    function init(map) {
        _injectStyles();
        var state = {
            markers: [], markerGroup: L.layerGroup(),
            linesLayer: null, linesOnMap: false, markersOnMap: false,
            selectedStation: null, highlightedRoute: null
        };
        var base = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';

        // Card click → highlight route line
        $('#ogrid-results-list').on('click', '.ogrid-result-card[data-metra-route]', function() {
            var routeId = $(this).attr('data-metra-route');
            if (state.highlightedRoute === routeId) {
                _clearLineHighlight(state);
            } else {
                _highlightRoute(routeId, state, map);
            }
        });

        map.on('click', function() { _clearLineHighlight(state); });

        $.ajax({ url: base + '/stations/metra-stations', type: 'GET', timeout: 30000 })
            .done(function(stops) {
                console.log('[MetraLayer] stations loaded:', (stops || []).length);
                var zoom = map.getZoom();
                (stops || []).forEach(function(stop) {
                    var m = _buildMarker(stop, state, zoom, base);
                    state.markers.push(m);
                    m.addTo(state.markerGroup);
                });
                _updateVisibility(map, state);
            })
            .fail(function(xhr, status, err) {
                console.warn('[MetraLayer] stations failed:', status, err);
            });

        $.ajax({ url: base + '/stations/metra-lines', type: 'GET', timeout: 60000 })
            .done(function(linesGeo) {
                console.log('[MetraLayer] lines loaded:', (linesGeo && linesGeo.features || []).length, 'features');
                if (linesGeo && linesGeo.features && linesGeo.features.length) {
                    state.linesLayer = L.geoJSON(linesGeo, {
                        style: function(f) {
                            return {
                                color:    f.properties.color || METRA_BLUE,
                                weight:   3,
                                opacity:  0.8,
                                lineJoin: 'round',
                                lineCap:  'round'
                            };
                        }
                    });
                    _updateVisibility(map, state);
                }
            })
            .fail(function(xhr, status, err) {
                console.warn('[MetraLayer] lines failed:', status, err);
            });

        map.on('zoomend', function() { _updateVisibility(map, state); });
    }

    var _attempts = 0;
    var _poll = setInterval(function() {
        _attempts++;
        try {
            var map = ogrid.App.map().getMap();
            if (map) { clearInterval(_poll); init(map); }
        } catch (e) {}
        if (_attempts >= 30) clearInterval(_poll);
    }, 500);
}());

/*
 * CTALayer — persistent CTA El train stations and rail lines.
 *
 * Rail lines:      visible zoom 16+, colored by route from GTFS.
 * Station icons:   visible zoom 12+, proportionally scaled with zoom.
 * Station labels:  visible zoom 16+.
 * Click a station: highlights its lines, fetches real-time arrivals,
 *                  displays each arrival as an ogrid-result-card sorted
 *                  by arrival time.
 */
(function () {
    var LINE_COLORS = {
        red:  '#c60c30', blue: '#00a1de', g:   '#009b3a',
        brn:  '#62361b', p:   '#522398', pexp:'#522398',
        y:    '#f9e300', pnk: '#e27ea6', o:   '#f9461c'
    };
    var LINE_DISPLAY = {
        red: 'Red', blue: 'Blue', g: 'Green', brn: 'Brown',
        p: 'Purple', pexp: 'Purple Express', y: 'Yellow', pnk: 'Pink', o: 'Orange'
    };
    var LINE_KEY_TO_ROUTE_ID = {
        red: 'red', blue: 'blue', g: 'g', brn: 'brn',
        p: 'p', pexp: 'pexp', y: 'y', pnk: 'pink', o: 'org'
    };
    var RT_TO_KEY = {
        Red: 'red', Blue: 'blue', G: 'g', Brn: 'brn',
        P: 'p', Pexp: 'pexp', Y: 'y', Pink: 'pnk', Org: 'o'
    };

    var LINES_ZOOM    = 16;
    var STATIONS_ZOOM = 14;
    var LABELS_ZOOM   = 16;

    // --- icon scaling -------------------------------------------------------

    function _iconSpec(zoom) {
        if (zoom >= 16) return { size: 22, border: 2,   fa: true  };
        if (zoom >= 15) return { size: 19, border: 2,   fa: true  };
        if (zoom >= 14) return { size: 16, border: 1.5, fa: true  };
        if (zoom >= 13) return { size: 12, border: 1.5, fa: false };
        if (zoom >= 12) return { size: 9,  border: 1,   fa: false };
        return                  { size: 7,  border: 1,   fa: false };
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
                ? '<i class="fa fa-subway" style="color:#ecf0f1;font-size:' + fa + 'px;line-height:1;"></i>'
                : '';
            _iconCache[key] = L.divIcon({
                className: 'ogrid-cta-marker',
                html: '<div style="width:' + s + 'px;height:' + s + 'px;' +
                      'background:#555;border:' + spec.border + 'px solid #ecf0f1;' +
                      'border-radius:50%;display:flex;align-items:center;' +
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

    function _lineBadges(lines) {
        return (lines || []).map(function(l) {
            var name  = LINE_DISPLAY[l] || l;
            var color = LINE_COLORS[l] || '#444';
            var text  = (l === 'y') ? '#000' : '#fff';
            return '<span style="display:inline-block;background:' + color +
                   ';color:' + text + ';padding:1px 7px;border-radius:3px;' +
                   'font-size:0.85em;margin:1px 2px;">' + _esc(name) + '</span>';
        }).join('');
    }

    function _stationHtml(st) {
        return '<div style="margin:2px 0 4px;">' + _lineBadges(st.lines) + '</div>' +
               (st.ada ? '<div style="font-size:0.82em;opacity:0.6;">&#x267F; Accessible</div>' : '');
    }

    // --- arrival cards ------------------------------------------------------

    function _pillLabel(a) {
        var label = (a.is_app || a.minutes <= 0) ? 'Due' :
                    a.minutes === 1 ? '1 min' : a.minutes + ' min';
        if (a.is_sch) label += '*';
        return label;
    }

    function _arrivalCard(a, destNm, rt) {
        var key    = RT_TO_KEY[rt] || '';
        var color  = LINE_COLORS[key] || '#555';
        var line   = (LINE_DISPLAY[key] || rt) + ' Line';
        var sub    = line + (a.is_dly ? ' &middot; Delayed' : '');
        var pill   = '<span class="rc-pill">' + _esc(_pillLabel(a)) + '</span>';
        var toggle = '<button type="button" class="rc-toggle" aria-label="Toggle details">' +
                     '<i class="fa fa-chevron-down"></i></button>';
        var detail = a.is_sch
            ? '<div class="rc-row"><span class="rc-k">Estimate</span><span class="rc-v">Scheduled (not real-time)</span></div>'
            : '<div class="rc-row"><span class="rc-k">Estimate</span><span class="rc-v">Real-time</span></div>';
        if (a.is_dly) {
            detail += '<div class="rc-row"><span class="rc-k">Status</span><span class="rc-v">Delayed</span></div>';
        }
        return '<div class="ogrid-result-card" style="border-left-color:' + color + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(destNm) + '</div>' +
               '<div class="rc-top-right">' + pill + toggle + '</div>' +
               '</div>' +
               '<div class="rc-sub">' + sub + '</div>' +
               '<div class="rc-details">' + detail + '</div>' +
               '</div>';
    }

    function _arrivalsHtml(groups) {
        if (!groups || !groups.length) {
            return '<div class="ogrid-empty">No arrivals currently scheduled.</div>';
        }
        var all = [];
        groups.forEach(function(g) {
            (g.arrivals || []).forEach(function(a) {
                all.push({ a: a, destNm: g.dest_nm, rt: g.rt });
            });
        });
        all.sort(function(x, y) { return x.a.minutes - y.a.minutes; });
        return all.map(function(item) {
            return _arrivalCard(item.a, item.destNm, item.rt);
        }).join('');
    }

    function _fetchArrivals(mapId, base) {
        $.ajax({ url: base + '/stations/cta-arrivals', data: { mapid: mapId }, timeout: 12000 })
            .done(function(groups) {
                $('.cta-arrivals-placeholder').replaceWith(_arrivalsHtml(groups));
            })
            .fail(function() {
                $('.cta-arrivals-placeholder').text('Arrivals unavailable.');
            });
    }

    // --- line highlighting --------------------------------------------------

    function _highlightLines(lines, state) {
        if (!state.linesLayer || !lines || !lines.length) return;
        var matchIds = {};
        lines.forEach(function(l) { matchIds[LINE_KEY_TO_ROUTE_ID[l] || l] = true; });
        state.linesLayer.eachLayer(function(layer) {
            var rid = (layer.feature.properties.route_id || '').toLowerCase();
            if (matchIds[rid]) {
                layer.setStyle({ weight: 5, opacity: 1.0 });
                if (state.linesOnMap) { layer.bringToFront(); }
            } else {
                layer.setStyle({ weight: 2, opacity: 0.25 });
            }
        });
    }

    function _clearHighlight(state) {
        if (state.linesLayer) {
            state.linesLayer.eachLayer(function(layer) {
                layer.setStyle({ weight: 3, opacity: 0.85 });
            });
        }
        state.selectedStation = null;
    }

    // --- markers ------------------------------------------------------------

    function _buildMarker(st, state, zoom, base) {
        var m = L.marker([st.lat, st.lon], { icon: _iconForZoom(zoom), zIndexOffset: 500 });
        m._ctaStationName = st.station_name;
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(m, {
                lat: st.lat,
                lon: st.lon,
                title: st.station_name
            });
        }
        m.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(m);
            }
            var wasSelected = (state.selectedStation === m);
            _clearHighlight(state);
            if (!wasSelected) {
                _highlightLines(st.lines, state);
                state.selectedStation = m;
            }
            if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
                ogrid.App._rp.showStationContent({
                    title: st.station_name,
                    html: _stationHtml(st) +
                          '<div class="cta-arrivals-placeholder" ' +
                          'style="margin-top:8px;font-size:12px;opacity:0.6;">Loading arrivals&hellip;</div>'
                });
            }
            _fetchArrivals(st.map_id, base);
        });
        return m;
    }

    // --- zoom visibility + resizing -----------------------------------------

    function _syncLabels(markers, zoom) {
        var show = zoom >= LABELS_ZOOM;
        markers.forEach(function(m) {
            if (show && !m.getTooltip()) {
                m.bindTooltip(m._ctaStationName || '', {
                    permanent: true, direction: 'right',
                    className: 'ogrid-cta-label', offset: [6, 0]
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

        if (state.linesLayer) {
            if (zoom >= LINES_ZOOM && !state.linesOnMap) {
                state.linesLayer.addTo(map); state.linesOnMap = true;
            } else if (zoom < LINES_ZOOM && state.linesOnMap) {
                state.linesLayer.remove(); state.linesOnMap = false;
                _clearHighlight(state);
            }
        }

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
            '.ogrid-cta-marker{background:transparent;border:none;}' +
            '.ogrid-cta-label.leaflet-tooltip{background:transparent!important;border:none!important;' +
            '  box-shadow:none!important;color:#555!important;font-size:11px!important;' +
            '  font-weight:bold!important;padding:2px 5px!important;white-space:nowrap!important;' +
            '  text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,' +
            '    0 0 5px rgba(255,255,255,0.9)!important;}' +
            '.ogrid-cta-label.leaflet-tooltip::before{display:none!important;}';
        document.head.appendChild(s);
    }

    // --- init ---------------------------------------------------------------

    function init(map) {
        _injectStyles();
        var state = {
            markers: [], markerGroup: L.layerGroup(),
            linesLayer: null, linesOnMap: false, markersOnMap: false,
            selectedStation: null
        };
        var base = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';

        map.on('click', function() { _clearHighlight(state); });

        $.ajax({ url: base + '/stations/cta-trains', type: 'GET', timeout: 20000 })
            .done(function(stList) {
                console.log('[CTALayer] stations loaded:', (stList || []).length);
                var zoom = map.getZoom();
                (stList || []).forEach(function(st) {
                    var m = _buildMarker(st, state, zoom, base);
                    state.markers.push(m);
                    m.addTo(state.markerGroup);
                });
                _updateVisibility(map, state);
            })
            .fail(function(xhr, status, err) {
                console.warn('[CTALayer] stations failed:', status, err);
            });

        $.ajax({ url: base + '/stations/cta-lines', type: 'GET', timeout: 60000 })
            .done(function(linesGeo) {
                console.log('[CTALayer] lines loaded:', (linesGeo && linesGeo.features || []).length, 'features');
                if (linesGeo && linesGeo.features && linesGeo.features.length) {
                    state.linesLayer = L.geoJSON(linesGeo, {
                        style: function(f) {
                            return { color: f.properties.color || '#555',
                                     weight: 3, opacity: 0.85,
                                     lineJoin: 'round', lineCap: 'round' };
                        }
                    });
                    _updateVisibility(map, state);
                }
            })
            .fail(function(xhr, status, err) {
                console.warn('[CTALayer] lines failed:', status, err);
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

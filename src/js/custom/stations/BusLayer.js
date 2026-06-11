/*
 * BusLayer — persistent CTA bus stop markers, viewport-loaded at zoom 17+.
 *
 * Stops are fetched for the current map bounds from /stations/bus-stops
 * and refreshed on pan/zoom. Click a stop → show real-time arrivals as
 * ogrid-result-cards sorted by arrival time.
 */
(function () {
    var CTA_BLUE  = '#00a1de';
    var STOPS_ZOOM = 17;

    var _BUS_ICON = L.divIcon({
        className: 'ogrid-bus-marker',
        html: '<div class="ogrid-bus-icon-wrap"><i class="fa fa-bus"></i></div>',
        iconSize:    [18, 18],
        iconAnchor:  [9, 9],
        popupAnchor: [0, -11]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // --- arrival cards ------------------------------------------------------

    function _pillLabel(a) {
        if (a.is_due || a.minutes <= 0) return 'Due';
        return a.minutes === 1 ? '1 min' : a.minutes + ' min';
    }

    function _arrivalCard(a) {
        var title  = _esc(a.rt + ' → ' + a.des);
        var pill   = '<span class="rc-pill">' + _esc(_pillLabel(a)) + '</span>';
        var toggle = '<button type="button" class="rc-toggle" aria-label="Toggle details">' +
                     '<i class="fa fa-chevron-down"></i></button>';
        var sub    = _esc(a.rtdir) + (a.is_dly ? ' &middot; Delayed' : '');
        var detail = '<div class="rc-row"><span class="rc-k">Direction</span>' +
                     '<span class="rc-v">' + _esc(a.rtdir) + '</span></div>';
        if (a.is_dly) {
            detail += '<div class="rc-row"><span class="rc-k">Status</span>' +
                      '<span class="rc-v">Delayed</span></div>';
        }
        return '<div class="ogrid-result-card" style="border-left-color:' + CTA_BLUE + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + title + '</div>' +
               '<div class="rc-top-right">' + pill + toggle + '</div>' +
               '</div>' +
               '<div class="rc-sub">' + sub + '</div>' +
               '<div class="rc-details">' + detail + '</div>' +
               '</div>';
    }

    function _arrivalsHtml(arrivals) {
        if (!arrivals || !arrivals.length) {
            return '<div class="ogrid-empty">No arrivals currently scheduled.</div>';
        }
        return arrivals.map(function(a) { return _arrivalCard(a); }).join('');
    }

    function _fetchArrivals(stop, base) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: stop.stop_name,
                html: '<div class="cta-arrivals-placeholder" ' +
                      'style="margin-top:8px;font-size:12px;opacity:0.6;">Loading arrivals&hellip;</div>'
            });
        }
        $.ajax({ url: base + '/stations/bus-arrivals', data: { stpid: stop.stop_id }, timeout: 12000 })
            .done(function(arrivals) {
                $('.cta-arrivals-placeholder').replaceWith(_arrivalsHtml(arrivals));
            })
            .fail(function() {
                $('.cta-arrivals-placeholder').text('Arrivals unavailable.');
            });
    }

    // --- markers ------------------------------------------------------------

    function _buildMarker(stop, base) {
        var m = L.marker([stop.lat, stop.lon], { icon: _BUS_ICON, zIndexOffset: 200 });
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
            _fetchArrivals(stop, base);
        });
        return m;
    }

    // --- viewport loading ---------------------------------------------------

    function _loadForBounds(bounds, state, base) {
        state.markerGroup.clearLayers();
        $.ajax({
            url:     base + '/stations/bus-stops',
            data:    {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: 15000
        }).done(function(stops) {
            (stops || []).forEach(function(stop) {
                _buildMarker(stop, base).addTo(state.markerGroup);
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

    // --- styles -------------------------------------------------------------

    function _injectStyles() {
        var s = document.createElement('style');
        s.textContent =
            '.ogrid-bus-marker{background:transparent;border:none;}' +
            '.ogrid-bus-icon-wrap{width:18px;height:18px;background:' + CTA_BLUE + ';' +
            '  border:2px solid #ecf0f1;border-radius:50%;display:flex;' +
            '  align-items:center;justify-content:center;cursor:pointer;' +
            '  box-shadow:0 1px 3px rgba(0,0,0,0.4);}' +
            '.ogrid-bus-icon-wrap .fa{color:#ecf0f1;font-size:8px;line-height:1;}';
        document.head.appendChild(s);
    }

    // --- init ---------------------------------------------------------------

    function init(map) {
        _injectStyles();
        var state = { markerGroup: L.layerGroup(), onMap: false };
        var base  = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';

        map.on('moveend', function() { _update(map, state, base); });
        map.on('zoomend', function() { _update(map, state, base); });
        _update(map, state, base);
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

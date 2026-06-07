/*
 * WebcamLayer — permanent map markers for webcams and sensor stations.
 *
 * To add a new camera, append an entry to the WEBCAMS array below.
 * The engine handles marker creation, zoom-based visibility, popup rendering,
 * and optional live data fetching. No other files need to change.
 *
 * Media types supported:
 *   'still'  — refreshing JPEG/PNG image (<img>)
 *   'video'  — HTML5 video element (<video autoplay muted>)
 *   'iframe' — embedded stream or player (<iframe>)
 */

// =============================================================================
// WEBCAM DEFINITIONS — add new cameras here
// =============================================================================
var WEBCAMS = [
    {
        id:       'dever-crib',
        name:     'Dever Crib',
        subtitle: 'Weather Station',
        lat:      41.916389,
        lon:      -87.573056,
        minZoom:  14,

        media: {
            type: 'still',
            url:  'https://www.glerl.noaa.gov/metdata/chi/chi01.jpg',
            alt:  'Dever Crib camera view'
        },

        dataEndpoint: '/stations/dever-crib',

        sourceUrl:  'https://www.glerl.noaa.gov/metdata/chi/',
        sourceName: 'GLERL Chicago Station',

        // Returns HTML rows shown below the image. Return '' to show nothing.
        renderData: function(d) {
            return '<b>Air:</b> ' + d.air_temp_c + '°C (' + d.air_temp_f + '°F)<br>' +
                   '<b>Wind:</b> ' + d.wind_avg_ms + ' m/s from ' + d.wind_dir_cardinal +
                       ' (max ' + d.wind_max_ms + ' m/s)<br>' +
                   '<b>Humidity:</b> ' + d.humidity_pct + '%<br>' +
                   '<span style="font-size:0.82em;opacity:0.65;">Observed: ' + d.observed + '</span>';
        }
    }

    // Example: add more cameras below
    // -------------------------------------------------------------------------
    // {
    //     id:       'navy-pier',
    //     name:     'Navy Pier',
    //     subtitle: 'Live Cam',
    //     lat:      41.8917,
    //     lon:      -87.6086,
    //     minZoom:  10,
    //     media: { type: 'iframe', url: 'https://example.com/navypier-stream', alt: 'Navy Pier' },
    //     sourceUrl:  'https://example.com/',
    //     sourceName: 'Chicago Webcams'
    // }
];

// =============================================================================
// ENGINE — no changes needed below this line to add new cameras
// =============================================================================
(function() {

    // Inject shared styles once
    var _style = document.createElement('style');
    _style.textContent = [
        '.ogrid-station-marker{background:transparent;border:none;}',
        '.ogrid-station-icon-wrap{',
        '  width:28px;height:28px;background:#1565C0;border:2px solid #ecf0f1;',
        '  border-radius:50%;display:flex;align-items:center;justify-content:center;',
        '  cursor:pointer;box-shadow:0 2px 5px rgba(0,0,0,0.5);}',
        '.ogrid-station-icon-wrap .fa{color:#ecf0f1;font-size:13px;line-height:1;}',
        '.ogrid-station-label.leaflet-tooltip{',
        '  background:transparent!important;border:none!important;',
        '  box-shadow:none!important;color:#1565C0!important;',
        '  font-size:11px!important;font-weight:bold!important;',
        '  padding:3px 8px!important;white-space:nowrap!important;',
        '  text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,',
        '    -2px 0 0 #fff,2px 0 0 #fff,0 -2px 0 #fff,0 2px 0 #fff,',
        '    0 2px 6px rgba(0,0,0,0.5)!important;}',
        '.ogrid-station-label.leaflet-tooltip::before{display:none!important;}'
    ].join('');
    document.head.appendChild(_style);

    var _icon = L.divIcon({
        className: 'ogrid-station-marker',
        html: '<div class="ogrid-station-icon-wrap"><i class="fa fa-camera"></i></div>',
        iconSize:    [28, 28],
        iconAnchor:  [14, 14],
        popupAnchor: [0, -18]
    });

    function _renderMedia(media) {
        if (!media) return '';
        if (media.type === 'still') {
            return '<img src="' + media.url + '" alt="' + (media.alt || '') + '" ' +
                'style="width:100%;display:block;border-radius:3px;margin-bottom:8px;">';
        }
        if (media.type === 'video') {
            return '<video src="' + media.url + '" autoplay muted playsinline loop ' +
                'style="width:100%;display:block;border-radius:3px;margin-bottom:8px;"></video>';
        }
        if (media.type === 'iframe') {
            return '<iframe src="' + media.url + '" frameborder="0" allowfullscreen ' +
                'style="width:100%;height:180px;display:block;border-radius:3px;margin-bottom:8px;"></iframe>';
        }
        return '';
    }

    function _renderSource(cam) {
        if (!cam.sourceUrl) return '';
        var name = cam.sourceName || cam.sourceUrl;
        return '<b>Source:</b> <a href="' + cam.sourceUrl + '" target="_blank" ' +
            'style="color:#82b1ff;">' + name + '</a><br>';
    }

    function _popupHtml(cam, data, error) {
        var media = _renderMedia(cam.media);
        var body;
        if (error) {
            body = '<span style="opacity:0.6;">Conditions unavailable.</span><br>';
        } else if (data === null) {
            body = !cam.dataEndpoint ? '' :
                '<span style="opacity:0.6;">Loading conditions…</span><br>';
        } else {
            body = cam.renderData ? cam.renderData(data) + '<br>' : '';
        }
        return media + body + _renderSource(cam);
    }

    function _initCam(cam, map) {
        var marker = L.marker([cam.lat, cam.lon], {icon: _icon, zIndexOffset: 1000})
            .bindTooltip(cam.name + '<br>' + cam.subtitle, {
                permanent:  true,
                direction:  'right',
                className:  'ogrid-station-label',
                offset:     [4, 0]
            });

        var onMap = false;

        function updateVisibility() {
            var zoom = map.getZoom();
            if (zoom >= cam.minZoom && !onMap) {
                marker.addTo(map);
                onMap = true;
            } else if (zoom < cam.minZoom && onMap) {
                marker.remove();
                onMap = false;
            }
        }

        marker.on('click', function() {
            var title = (cam.name || '') + (cam.subtitle ? ' ' + cam.subtitle : '');
            var show = function(data, error) {
                if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
                    ogrid.App._rp.showStationContent({ title: title, html: _popupHtml(cam, data, error) });
                }
            };
            show(null, false);   // image + loading state

            if (!cam.dataEndpoint) return;

            var url = ogrid.Config.service.endpoint
                .replace(/\/rest\/?$/, '') + '/rest' + cam.dataEndpoint;

            $.ajax({
                url: url, type: 'GET', timeout: 12000,
                success: function(d) { show(d, false); },
                error:   function()  { show(null, true); }
            });
        });

        map.on('zoomend', updateVisibility);
        updateVisibility();
    }

    // Wait for the Leaflet map, then initialize all cameras
    var attempts = 0;
    var poll = setInterval(function() {
        attempts++;
        try {
            var map = ogrid.App.map().getMap();
            if (map) {
                clearInterval(poll);
                for (var i = 0; i < WEBCAMS.length; i++) {
                    _initCam(WEBCAMS[i], map);
                }
            }
        } catch(e) {}
        if (attempts >= 30) clearInterval(poll);
    }, 500);

}());

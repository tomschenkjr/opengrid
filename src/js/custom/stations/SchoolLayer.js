/*
 * SchoolLayer — persistent CPS school markers from School Progress Reports.
 *
 * Schools are shown one zoom step before bus stops and loaded for the current
 * viewport from /stations/schools. Clicking a school opens profile and
 * performance details in the Results Pane.
 */
(function () {
    var SCHOOL_GREEN = '#4D7C0F';
    var SCHOOLS_ZOOM = 16;

    var _SCHOOL_ICON = L.divIcon({
        className: 'ogrid-school-marker',
        html: '<div class="ogrid-school-icon-wrap"><i class="fa fa-book"></i></div>',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -11]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _fmt(v) {
        return v == null || v === '' ? 'n/a' : _esc(v);
    }

    function _pct(v) {
        if (v == null || v === '') {
            return 'n/a';
        }
        return _esc(v) + '%';
    }

    function _row(label, value, isPct) {
        if (value == null || value === '') {
            return '';
        }
        return '<div class="rc-row"><span class="rc-k">' + _esc(label) + '</span>' +
               '<span class="rc-v">' + (isPct ? _pct(value) : _fmt(value)) + '</span></div>';
    }

    function _detailCard(school) {
        var sub = [_fmt(school.school_type), _fmt(school.address), _fmt(school.zip)]
            .filter(function(v) { return v && v !== 'n/a'; }).join(' &middot; ');
        var details =
            _row('Culture Climate', school.culture_climate_rating) +
            _row('Student Growth', school.student_growth_rating) +
            _row('Student Attainment', school.student_attainment_rating) +
            _row('Safety Survey', school.school_survey_safety) +
            _row('Student Attendance', school.student_attendance_year_2, true) +
            _row('Teacher Attendance', school.teacher_attendance_avg_pct, true) +
            _row('Chronic Truancy', school.chronic_truancy_pct, true) +
            _row('Freshmen On Track', school.freshmen_on_track_school_1, true) +
            _row('4-Year Graduation', school.graduation_4_year_school_1, true) +
            _row('College Enrollment', school.college_enrollment_school_1, true) +
            _row('SAT Grade 11 Avg', school.sat_grade_11_score_school) +
            _row('Progress Report Year', school.progress_report_year) +
            _row('Phone', school.phone);
        return '<div class="ogrid-result-card ogrid-school-result-card expanded" style="border-left-color:' + SCHOOL_GREEN + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(school.long_name || 'CPS School') + '</div>' +
               '<div class="rc-top-right"><span class="rc-pill ogrid-school-pill">' + _esc(school.primary_category || 'School') + '</span></div>' +
               '</div>' +
               (sub ? '<div class="rc-sub">' + sub + '</div>' : '') +
               '<div class="rc-details">' + (details || '<div class="rc-row">No school metrics available.</div>') + '</div>' +
               '</div>';
    }

    function _showSchool(school) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: 'CPS School',
                html: _detailCard(school)
            });
        }
    }

    function _buildMarker(school) {
        var marker = L.marker([school.lat, school.lon], { icon: _SCHOOL_ICON, zIndexOffset: 190 });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: school.lat,
                lon: school.lon,
                title: school.long_name || 'CPS School'
            });
        }
        marker.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            _showSchool(school);
        });
        return marker;
    }

    function _loadForBounds(bounds, state, base) {
        state.markerGroup.clearLayers();
        $.ajax({
            url: base + '/stations/schools',
            data: {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: 15000
        }).done(function(schools) {
            (schools || []).forEach(function(school) {
                _buildMarker(school).addTo(state.markerGroup);
            });
        });
    }

    function _update(map, state, base) {
        var zoom = map.getZoom();
        if (zoom >= SCHOOLS_ZOOM) {
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

    function _injectStyles() {
        if (document.getElementById('ogrid-school-layer-style')) {
            return;
        }
        var s = document.createElement('style');
        s.id = 'ogrid-school-layer-style';
        s.textContent =
            '.ogrid-school-marker{background:transparent;border:none;}' +
            '.ogrid-school-icon-wrap{width:18px;height:18px;background:' + SCHOOL_GREEN + ';' +
            'border:2px solid #ecf0f1;border-radius:50%;display:flex;' +
            'align-items:center;justify-content:center;cursor:pointer;' +
            'box-shadow:0 1px 3px rgba(0,0,0,0.4);}' +
            '.ogrid-school-icon-wrap .fa{color:#ecf0f1;font-size:8px;line-height:1;}' +
            '.ogrid-result-card.ogrid-school-result-card{cursor:default;}' +
            '.ogrid-school-pill{color:' + SCHOOL_GREEN + ';border-color:' + SCHOOL_GREEN + ';white-space:normal;text-align:left;}';
        document.head.appendChild(s);
    }

    function init(map) {
        _injectStyles();
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

/*
 * ogrid.ProfileCharts
 *
 * Thin Chart.js 2.4.0 helpers for the Community Profile page: doughnut/pie, bar
 * (histogram / column), and grouped bar. Each returns a Chart instance so the caller
 * can destroy() it before re-rendering. Uses a fixed teal palette to match the design.
 *
 * Chart.js and chroma are already global (lib bundle). All value labels are drawn
 * defensively (try/catch) so a label-drawing hiccup never blanks the chart.
 */
ogrid.ProfileCharts = (function () {

    var TEAL = '#4f9c95';
    var SALMON = '#e3a597';
    // Teal-centric categorical palette for multi-slice pies / column charts.
    var PALETTE = ['#4f9c95', '#e3a597', '#7fbfb7', '#cf9a6e', '#2e6e68',
                   '#9cc7c2', '#c97f72', '#bcd6d2', '#6a928d', '#e8c9a0'];

    function color(i) { return PALETTE[i % PALETTE.length]; }

    function pctOf(value, total) {
        if (!total) { return 0; }
        return Math.round(value / total * 100);
    }

    // ---- Doughnut / pie --------------------------------------------------- #
    function pie(canvas, slices) {
        var total = slices.reduce(function (s, x) { return s + (x.value || 0); }, 0);
        var labels = slices.map(function (x) { return x.label + ' ' + pctOf(x.value, total) + '%'; });
        var colors = slices.map(function (x, i) { return color(i); });

        // Largest slice → center label (mirrors the mock's big % in the hole).
        var top = slices.reduce(function (a, b) { return (b.value > a.value) ? b : a; }, slices[0] || {});
        var centerPct = pctOf(top.value || 0, total);
        var centerLabel = top.label || '';

        return new Chart(canvas.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{ data: slices.map(function (x) { return x.value; }),
                             backgroundColor: colors, borderColor: '#fff', borderWidth: 2 }]
            },
            options: {
                responsive: true, maintainAspectRatio: false, cutoutPercentage: 62,
                legend: { position: 'right', labels: { boxWidth: 12, fontSize: 11, padding: 8 } },
                tooltips: { callbacks: { label: function (item, data) {
                    var v = data.datasets[0].data[item.index];
                    return data.labels[item.index].replace(/ \d+%$/, '') +
                           ': ' + v.toLocaleString() + ' (' + pctOf(v, total) + '%)';
                } } },
                animation: { onComplete: function () {
                    try {
                        var ch = this.chart, ctx = ch.ctx;
                        var cx = (ch.chartArea.left + ch.chartArea.right) / 2;
                        var cy = (ch.chartArea.top + ch.chartArea.bottom) / 2;
                        ctx.save();
                        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                        ctx.fillStyle = '#2c3e50';
                        ctx.font = '700 18px Helvetica, Arial, sans-serif';
                        ctx.fillText(centerPct + '%', cx, cy - 4);
                        ctx.fillStyle = '#6b7785';
                        ctx.font = '600 10px Helvetica, Arial, sans-serif';
                        ctx.fillText(centerLabel, cx, cy + 13);
                        ctx.restore();
                    } catch (e) { /* center label is decorative */ }
                } }
            }
        });
    }

    // ---- Bar (histogram / column) ---------------------------------------- #
    // opts.percent → label bars with their share of the total; else raw counts.
    function bars(canvas, bins, opts) {
        opts = opts || {};
        var total = bins.reduce(function (s, x) { return s + (x.value || 0); }, 0);
        var labelText = bins.map(function (x) {
            return opts.percent ? (pctOf(x.value, total) + '%') : shortNum(x.value);
        });

        return new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: bins.map(function (x) { return x.label; }),
                datasets: [{ data: bins.map(function (x) { return x.value; }),
                             backgroundColor: TEAL, borderWidth: 0, maxBarThickness: 64 }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                legend: { display: false },
                tooltips: { callbacks: { label: function (item) {
                    return item.yLabel.toLocaleString() + ' (' + pctOf(item.yLabel, total) + '%)';
                } } },
                scales: {
                    xAxes: [{ gridLines: { display: false },
                              ticks: { fontSize: 10, fontColor: '#6b7785', maxRotation: 40, minRotation: 0 } }],
                    yAxes: [{ display: false, ticks: { beginAtZero: true } }]
                },
                layout: { padding: { top: 18 } },
                animation: { onComplete: function () { _drawBarLabels(this, labelText); } }
            }
        });
    }

    // ---- Grouped bar ------------------------------------------------------ #
    function groupedBars(canvas, categories, series) {
        return new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: categories,
                datasets: series.map(function (s, i) {
                    return { label: s.label, data: s.values,
                             backgroundColor: i === 0 ? TEAL : SALMON, borderWidth: 0, maxBarThickness: 40 };
                })
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                legend: { position: 'top', labels: { boxWidth: 12, fontSize: 11 } },
                tooltips: { callbacks: { label: function (item, data) {
                    return data.datasets[item.datasetIndex].label + ': ' + item.yLabel.toLocaleString();
                } } },
                scales: {
                    xAxes: [{ gridLines: { display: false }, ticks: { fontSize: 10, fontColor: '#6b7785' } }],
                    yAxes: [{ display: false, ticks: { beginAtZero: true } }]
                }
            }
        });
    }

    // ---- Stacked single-column bar --------------------------------------- #
    function stackedColumn(canvas, segments) {
        segments = segments || [];
        var total = segments.reduce(function (s, x) { return s + (x.value || 0); }, 0);

        return new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: ['Households'],
                datasets: segments.map(function (s, i) {
                    return { label: s.label, data: [s.value || 0],
                             backgroundColor: color(i), borderWidth: 0, maxBarThickness: 80 };
                })
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                legend: { position: 'right', labels: { boxWidth: 12, fontSize: 11, padding: 8 } },
                tooltips: { callbacks: { label: function (item, data) {
                    var ds = data.datasets[item.datasetIndex];
                    var v = ds.data[item.index] || 0;
                    return ds.label + ': ' + v.toLocaleString() + ' (' + pctOf(v, total) + '%)';
                } } },
                scales: {
                    xAxes: [{ stacked: true, gridLines: { display: false },
                              ticks: { fontSize: 10, fontColor: '#6b7785' } }],
                    yAxes: [{ stacked: true, display: false, ticks: { beginAtZero: true } }]
                }
            }
        });
    }

    // ---- Line chart ------------------------------------------------------- #
    function line(canvas, points, opts) {
        points = points || [];
        opts = opts || {};
        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: points.map(function (x) { return x.label; }),
                datasets: [{
                    data: points.map(function (x) { return x.value || 0; }),
                    borderColor: TEAL,
                    backgroundColor: 'rgba(79, 156, 149, 0.14)',
                    borderWidth: 2,
                    pointBackgroundColor: TEAL,
                    pointBorderColor: '#fff',
                    pointBorderWidth: 1,
                    pointRadius: 3,
                    lineTension: 0.25,
                    fill: true
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                legend: { display: false },
                tooltips: { callbacks: { label: function (item) {
                    return formatValue(item.yLabel, opts.format);
                } } },
                scales: {
                    xAxes: [{ gridLines: { display: false },
                              ticks: { fontSize: 10, fontColor: '#6b7785', maxRotation: 40, minRotation: 0 } }],
                    yAxes: [{ gridLines: { color: 'rgba(107,119,133,0.16)' },
                              ticks: { beginAtZero: true, callback: function(v) { return shortNum(v); },
                                       fontSize: 10, fontColor: '#6b7785' } }]
                },
                layout: { padding: { top: 8, right: 8, bottom: 0, left: 0 } }
            }
        });
    }

    // ---- Box-and-whisker comparison -------------------------------------- #
    function boxWhisker(canvas, spec) {
        spec = spec || {};
        var d = spec.distribution || {};
        var value = spec.value;
        var min = d.min, q1 = d.q1, median = d.median, q3 = d.q3, max = d.max, mean = d.mean;
        var ctx = canvas.getContext('2d');
        var parent = canvas.parentNode;
        var dpr = window.devicePixelRatio || 1;
        var cssW = Math.max(parent ? parent.clientWidth : 320, 280);
        var cssH = Math.max(parent ? parent.clientHeight : 180, 160);

        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
        canvas.style.width = cssW + 'px';
        canvas.style.height = cssH + 'px';
        ctx.scale(dpr, dpr);

        function fmt(v) { return formatValue(v, spec.format); }
        function x(v) {
            if (v == null || max === min) { return 0; }
            return left + ((v - min) / (max - min)) * (right - left);
        }

        var left = 46, right = cssW - 26;
        var cy = Math.round(cssH * 0.48);
        var boxTop = cy - 28, boxH = 42;

        ctx.clearRect(0, 0, cssW, cssH);
        ctx.font = '600 11px Helvetica, Arial, sans-serif';
        ctx.fillStyle = '#6b7785';
        ctx.textAlign = 'center';

        if ([min, q1, median, q3, max].some(function(v) { return v == null; })) {
            ctx.fillText('Hardship Index unavailable', cssW / 2, cy);
            return { destroy: function() {} };
        }

        ctx.strokeStyle = '#9cc7c2';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x(min), cy);
        ctx.lineTo(x(max), cy);
        ctx.stroke();

        [min, max].forEach(function(v) {
            ctx.beginPath();
            ctx.moveTo(x(v), cy - 18);
            ctx.lineTo(x(v), cy + 18);
            ctx.stroke();
        });

        ctx.fillStyle = 'rgba(79, 156, 149, 0.2)';
        ctx.strokeStyle = TEAL;
        ctx.lineWidth = 2;
        ctx.fillRect(x(q1), boxTop, Math.max(x(q3) - x(q1), 2), boxH);
        ctx.strokeRect(x(q1), boxTop, Math.max(x(q3) - x(q1), 2), boxH);

        ctx.strokeStyle = '#2e6e68';
        ctx.beginPath();
        ctx.moveTo(x(median), boxTop - 6);
        ctx.lineTo(x(median), boxTop + boxH + 6);
        ctx.stroke();

        if (mean != null) {
            ctx.fillStyle = SALMON;
            ctx.beginPath();
            ctx.arc(x(mean), cy, 5, 0, Math.PI * 2);
            ctx.fill();
        }

        if (value != null) {
            var vx = x(value);
            ctx.strokeStyle = '#c97f72';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(vx, boxTop - 16);
            ctx.lineTo(vx, boxTop + boxH + 16);
            ctx.stroke();
            ctx.fillStyle = '#2c3e50';
            ctx.font = '700 12px Helvetica, Arial, sans-serif';
            ctx.fillText('This area: ' + fmt(value), vx, boxTop - 22);
        }

        ctx.fillStyle = '#6b7785';
        ctx.font = '600 10px Helvetica, Arial, sans-serif';
        ctx.fillText(fmt(min), x(min), cssH - 28);
        ctx.fillText(fmt(max), x(max), cssH - 28);
        ctx.fillText('Median ' + fmt(median), x(median), cssH - 10);
        if (mean != null) { ctx.fillText('Avg ' + fmt(mean), x(mean), cy + 34); }

        return { destroy: function() { ctx.clearRect(0, 0, canvas.width, canvas.height); } };
    }

    // Draw a small label above each bar of a single-dataset bar chart.
    function _drawBarLabels(chart, labelText) {
        try {
            var ctx = chart.chart.ctx;
            ctx.save();
            ctx.font = '600 10px Helvetica, Arial, sans-serif';
            ctx.fillStyle = '#6b7785'; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
            var meta = chart.getDatasetMeta(0);
            meta.data.forEach(function (bar, i) {
                if (labelText[i] != null) { ctx.fillText(labelText[i], bar._model.x, bar._model.y - 2); }
            });
            ctx.restore();
        } catch (e) { /* bar labels are decorative */ }
    }

    function shortNum(v) {
        if (v == null) { return ''; }
        if (v >= 1000000) { return (Math.round(v / 100000) / 10) + 'M'; }
        if (v >= 10000) { return (Math.round(v / 100) / 10) + 'k'; }
        return Math.round(v).toLocaleString();
    }

    function formatValue(v, fmt) {
        if (v == null) { return ''; }
        if (fmt === 'currency') { return '$' + Math.round(v).toLocaleString(); }
        if (fmt === 'percent') { return Math.round(v) + '%'; }
        return Math.round(v).toLocaleString();
    }

    return { pie: pie, bars: bars, groupedBars: groupedBars,
             stackedColumn: stackedColumn, line: line, boxWhisker: boxWhisker, TEAL: TEAL };
})();

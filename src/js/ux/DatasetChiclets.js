/*
 * ogrid.DatasetChiclets
 *
 * Quick-access dataset chiclets shown next to the search box when the map has
 * no results (app start / after Clear). Each chiclet represents a dataset;
 * clicking one loads that dataset within the current map extent. Once data is
 * on the map the chiclets hide (and the Summarize button takes their place).
 */
ogrid.DatasetChiclets = ogrid.Class.extend({

    _options: {},

    init: function(options) {
        if (options) { this._options = $.extend(this._options, options); }
        var me = this;

        this._render();

        // Visible only when there is no data on the map
        ogrid.Event.on(ogrid.Event.types.CLEAR, function() {
            $('#ogrid-dataset-chiclets').removeClass('hide');
        });
        ogrid.Event.on(ogrid.Event.types.REFRESH_DATA, function() {
            $('#ogrid-dataset-chiclets').addClass('hide');
        });

        $('#ogrid-dataset-chiclets').on('click', '.ogrid-ds-chiclet', function() {
            me._load($(this).data('id'));
        });
    },

    _render: function() {
        // Use the dataset NAME as the chiclet label — plain words are clearer and
        // more discoverable than icons, which force users to guess what each one
        // means. Styled like the filter chiclets (.ogrid-chiclet > button).
        var html = (this._options.datasets || []).map(function(d) {
            return '<button type="button" class="ogrid-ds-chiclet" data-id="' + d.id + '" ' +
                   'title="' + d.displayName + '">' + d.displayName + '</button>';
        }).join('');
        $('#ogrid-dataset-chiclets').html(html);
    },

    _load: function(datasetId) {
        var bounds = null;
        try {
            var b = ogrid.App.map().getMap().getBounds();
            bounds = { minLat: b.getSouth(), minLon: b.getWest(), maxLat: b.getNorth(), maxLon: b.getEast() };
        } catch (e) {}

        var payload = { datasets: [datasetId], timeframe: 'all', community_area: null, bounds: bounds };
        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/search/filtered';
        var token = (typeof sessionStorage !== 'undefined') ? sessionStorage.getItem('auth_token') : null;

        $.ajax({
            url: url, type: 'POST', contentType: 'application/json',
            data: JSON.stringify(payload),
            headers: token ? { 'X-AUTH-TOKEN': token } : {},
            timeout: 60000
        }).done(function(res) {
            if (ogrid.App && ogrid.App._qs) { ogrid.App._qs._onExecDone(res); }
        }).fail(function() {
            ogrid.Alert.error('Unable to load dataset.');
        });
    }
});

ogrid.datasetChiclets = function(options) { return new ogrid.DatasetChiclets(options); };

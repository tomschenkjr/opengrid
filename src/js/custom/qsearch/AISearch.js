/*
 * ogrid.QSearchProcessor.AISearch
 *
 * Catch-all quick search processor that routes queries to the smart search endpoint.
 * Handles both POI/address lookups (via ArcGIS geocoder server-side) and
 * natural language data queries (via Claude + chicago-data-mcp).
 */

ogrid.QSearchProcessor.AISearch = ogrid.QSearchProcessor.extend({
    _options: {
        endpoint: null
    },

    init: function(options) {
        if (options) {
            this._options = $.extend(this._options, options);
        }
    },

    // Accepts anything not already claimed by LatLng or FlexData
    test: function(input) {
        return (input && $.trim(input).length > 0);
    },

    exec: function(input, onSuccess, onError) {
        var me = this;
        var endpoint = me._options.endpoint || ogrid.Config.service.endpoint;
        var url = endpoint.replace(/\/rest\/?$/, '') + '/rest/search/smart';

        var payload = { query: $.trim(input) };
        try {
            var mapBounds = ogrid.App.map().getMap().getBounds();
            payload.bounds = {
                minLat: mapBounds.getSouth(),
                minLon: mapBounds.getWest(),
                maxLat: mapBounds.getNorth(),
                maxLon: mapBounds.getEast()
            };
        } catch(e) {}

        $.ajax({
            url: url,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            headers: (function() {
                var token = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('auth_token') : null;
                return token ? { 'X-AUTH-TOKEN': token } : {};
            }()),
            timeout: 60000,
            success: function(data) {
                if (data && data.features !== undefined) {
                    onSuccess(data);
                } else {
                    onError('Unexpected response format from smart search');
                }
            },
            error: function(xhr, status, err) {
                onError(err || status);
            }
        });
    }
});

ogrid.QSearchProcessor.aiSearch = function(options) {
    return new ogrid.QSearchProcessor.AISearch(options);
};

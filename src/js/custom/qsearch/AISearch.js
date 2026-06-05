/*
 * ogrid.QSearchProcessor.AISearch
 *
 * Catch-all quick search processor that routes queries to the smart search endpoint.
 * Handles both POI/address lookups (via ArcGIS geocoder server-side) and
 * natural language data queries (via Claude + chicago-data-mcp).
 */

// Phrases that signal the user wants results near their current GPS position.
var _GEO_SELF_RE = /\b(near(?: me| here)|nearby|close to me|by me|around(?: me| here)?|from here|right here|in (?:my (?:neighborhood|area|vicinity|community|part of town|backyard|block|street)|this area)|at my (?:house|home|address)|where i live|near where i live|(?:my )?current location|my location|locally)\b/i;

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
        var trimmed = $.trim(input);

        if (_GEO_SELF_RE.test(trimmed) && navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function(pos) {
                    me._doSearch(trimmed, {lat: pos.coords.latitude, lon: pos.coords.longitude}, onSuccess, onError);
                },
                function() {
                    onError('Location access is required for this search. Please allow location access and try again.');
                },
                { timeout: 10000, maximumAge: 60000 }
            );
        } else {
            me._doSearch(trimmed, null, onSuccess, onError);
        }
    },

    _doSearch: function(input, currentLocation, onSuccess, onError) {
        var me = this;
        var endpoint = me._options.endpoint || ogrid.Config.service.endpoint;
        var url = endpoint.replace(/\/rest\/?$/, '') + '/rest/search/smart';

        var payload = { query: input };
        try {
            var mapBounds = ogrid.App.map().getMap().getBounds();
            payload.bounds = {
                minLat: mapBounds.getSouth(),
                minLon: mapBounds.getWest(),
                maxLat: mapBounds.getNorth(),
                maxLon: mapBounds.getEast()
            };
        } catch(e) {}

        if (currentLocation) {
            payload.current_location = currentLocation;
            console.log('[AISearch] current_location:', currentLocation);
        }

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
                if (data && (data.features !== undefined || data.layers !== undefined)) {
                    onSuccess(data);
                } else {
                    onError('Unexpected response format from smart search');
                }
            },
            error: function(xhr, status, err) {
                onError(err || status, {jqXHR: xhr, txtStatus: status, errorThrown: err});
            }
        });
    }
});

ogrid.QSearchProcessor.aiSearch = function(options) {
    return new ogrid.QSearchProcessor.AISearch(options);
};

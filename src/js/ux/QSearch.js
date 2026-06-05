/*
 * ogrid.QSearch
 *
 * Quick search UX component
 */

/*jshint  expr: true */

ogrid.QSearch = ogrid.Class.extend({
    //private attributes
    _options:{
        datasets: null
    },
    _qsContainer: null,
    _input: null,
    _qsbutton: null,
    _geoFilter: null,
    _mapMoveHandler: null,

    //public attributes


    //constructor
    init: function(qsdiv, qsinput, qsbutton, options) {
        if (options) {
            //ogrid.mixin(this._options);
            this._options = $.extend(this._options, options);
        }

        this._qsContainer = qsdiv;

        //setup event handlers on search control
        this._qsbutton = qsbutton;
        this._qsbutton.click($.proxy(this._onSearch, this));

       this._initPopup();

        this._input = qsinput;
        var me = this;

        this._input.keypress(function (e) {
            if (e.which == 13) {
                me._onSearch();
                return false;
            }
        });

        //subscribe to applicable opengrid client events
        ogrid.Event.on(ogrid.Event.types.CLEAR, $.proxy(this._onClear, this));
        ogrid.Event.on(ogrid.Event.types.LOGGED_IN, $.proxy(this._onLoggedIn, this));

        var me = this;
        $('#ogrid-search-again').on('click', function() {
            $(this).hide();
            me._onSearch();
        });

    },


    _initPopup: function(done) {
        var me = this;
        $.get(ogrid.Config.quickSearch.helpFile, function(data) {
            var $t = $('<div/>').html(data).contents();
            //var $t = $($.parseHTML(data));

            //builds html from new dataset quicksearch settings
            var hintHtml = '';
            if (me._options.datasets) {
                var hints = [];
                $.each(me._options.datasets, function(i, v) {
                    if (v.quickSearch && v.quickSearch.enable) {
                        v.quickSearch.hintCaption && (hintHtml += '<p><b>' + v.quickSearch.hintCaption + '</b><br>');
                        v.quickSearch.hintExample && (hintHtml += v.quickSearch.hintExample);
                        v.quickSearch.hintCaption && (hintHtml += '</p>');
                        v.quickSearch.hintDescription && (hintHtml += '<p><i>' + v.quickSearch.hintDescription + '</i><p>');
                    }
                });
            }
            $t.find('#ogrid-quicksearchhelp').append(hintHtml);
            var $o = $("[data-toggle=popover]").popover({
                html: true,
                content: $t.parent().html(),
                container: 'body'
                //title: 'Quick Search Help <a href="#" class="close" data-dismiss="alert">X</a>'
            });
        });
    },

    //private methods
    _findQSearchFlexDataPlugin: function() {
        var o = null;
        $.each(ogrid.Config.quickSearch.plugins, function(i,v) {
            if (v instanceof ogrid.QSearchProcessor.FlexData) {
                o = v;
                return false; //break
            }
        });
        return o;
    },


    _onLoggedIn: function(e) {
        //set initial focus to Quick Search input
        var me = this;
        try {
            this._input.prop('disabled', true);
            //set datasets option of FlexData quick search processor after login
            var o = this._findQSearchFlexDataPlugin();
            if (o) {
                //var dsCall = $.ajax(ogrid.Config.service.endpoint + '/datasets');
                //dsCall.then(function (dataTypes) {
                    o.setOptions({datasets: this._options.datasets});
                    me._input.prop('disabled', false);
                //});
            }
        } catch (ex) {
            console.log(ex.message);
        }
    },

    _onClear: function (evtData) {
        this._input.val('');
        $('#ogrid-search-again').hide();
        try {
            //avoid annoying keyboard popup when on mobile mode
            if (!ogrid.App.mobileView()) this._input.focus();
        } catch (e) {
            console.log(e.message);
        }
    },

        _onSearch: function(done) {
        // If main content is hidden remove it and disable help.
        if($("#ogrid-content").hasClass('hide')) {
            $("#ogrid-help").addClass('hide');
            $("#ogrid-content").removeClass('hide');
        }

        this._input.blur();

        //console.log("Quick Search clicked");
        if (this._input.val().trim().length === 0 ) {
            ogrid.Alert.error('No quick search command was entered.');
        } else {
            this._execSearch(this._input.val());
        }
    },

    _execSearch: function ( searchInput ) {
        //console.log('Quick search entered:' + searchInput);

        try {
            //parse and exec async
            ogrid.QSearchFactory.parse(searchInput).exec(searchInput, this._onExecDone.bind(this), this._onExecError);
        } catch (e) {
            //ogrid.Alert.modal('OpenGrid Error', e.message);
            ogrid.Alert.error(e.message);
        }
    },

    _getGeoFilterWidget: function() {
        var fakeContainer = $();
        var o =  ogrid.geoFilter(fakeContainer, {
                bounds: ogrid.Config.advancedSearch.geoFilterBoundaries,

                //no additional near refs aside from _map-click
                nearReferences: null,

                //pass the true map object
                map: ogrid.App.map().getMap(),
                geoLocationControl: ogrid.App.map().getGeoLocationControl()
            }
        );
        //this makes it map-extent by default
        o.reset();
        return o;
    },

    _isGeoFilterableData: function(data) {
        //we are using this indicator for data to be geo-Filter in quick search; might change in the future
        return (data.meta.view.options.rendition.icon !== "marker");
    },

    _onExecDone: function (results) {
        // Multi-dataset response: render each layer independently
        if (results.layers && results.layers.length > 0) {
            var me = this;
            var sharedBoundary = null;
            var multiLats = [], multiLons = [];

            $.each(results.layers, function(i, layer) {
                if (me._isGeoFilterableData(layer)) {
                    var c = layer.meta.view.options.rendition.color;
                    layer.meta.view.options.rendition.fillColor = (chroma.scale(['white', c])(0.5)).hex();
                }
                ogrid.Event.raise(ogrid.Event.types.REFRESH_DATA, {
                    resultSetId: ogrid.guid(),
                    data: layer,
                    options: { clear: i === 0, passthroughData: {} }
                });
                // Collect the boundary from the first layer that has one (all share the same geography)
                if (!sharedBoundary && layer.meta && layer.meta.geography_boundary) {
                    sharedBoundary = layer.meta.geography_boundary;
                }
                // Accumulate point coordinates for auto-fit
                if (layer.features) {
                    $.each(layer.features, function(j, f) {
                        if (f.geometry && f.geometry.type === 'Point' && f.geometry.coordinates) {
                            multiLons.push(f.geometry.coordinates[0]);
                            multiLats.push(f.geometry.coordinates[1]);
                        }
                    });
                }
            });

            // Render the shared boundary once on top of all data layers
            if (sharedBoundary) {
                ogrid.Event.raise(ogrid.Event.types.REFRESH_DATA, {
                    resultSetId: ogrid.guid(),
                    data: sharedBoundary,
                    options: { clear: false, passthroughData: {} }
                });
            }

            // Auto-fit to combined data extent, falling back to boundary if no points
            try {
                if (multiLats.length > 0) {
                    var sw = [Math.min.apply(null, multiLats), Math.min.apply(null, multiLons)];
                    var ne = [Math.max.apply(null, multiLats), Math.max.apply(null, multiLons)];
                    ogrid.App.map().getMap().fitBounds([sw, ne], { padding: [40, 40] });
                } else if (sharedBoundary) {
                    ogrid.App.map().getMap().fitBounds(
                        L.geoJSON(sharedBoundary).getBounds(), { padding: [40, 40] }
                    );
                }
            } catch(e) {}

            me._watchMapForSearchAgain();
            return;
        }

        var autoRequery = this._isGeoFilterableData(results);
        //if geoSpatial filtering is not supported by service, implement filtering locally
        if ( !ogrid.App.serviceCapabilities().geoSpatialFiltering && this._isGeoFilterableData(results)) {
            if ( !this._geoFilter ) {
                this._geoFilter = this._getGeoFilterWidget();
            }
            //apply additional geo-spatial filter, within map extent
            results = this._geoFilter.filterData(results);
        }

        //fix fillColor of points to make it consistent with Advanced Search
        if (this._isGeoFilterableData(results)) {
            var c = results.meta.view.options.rendition.color;
            results.meta.view.options.rendition.fillColor =  (chroma.scale(['white', c])(0.5)).hex();
        }

        var prox = results.meta && results.meta.proximity;
        if (prox) {
            ogrid.Alert.info('Showing results ' + prox.label + '.');
        }

        ogrid.Event.raise(ogrid.Event.types.REFRESH_DATA, {
            resultSetId:ogrid.guid(),
            data: results,
            options: {
                clear: true,
                passthroughData: {}  // no regenerator — map extent changes use the button instead
            }
        });

        // Overlay reference anchor locations without clearing the primary layer
        if (prox && prox.layer) {
            ogrid.Event.raise(ogrid.Event.types.REFRESH_DATA, {
                resultSetId: ogrid.guid(),
                data: prox.layer,
                options: { clear: false, passthroughData: {} }
            });
        }

        // Overlay geography boundary (community area / ward outline) if present
        var geoBoundary = results.meta && results.meta.geography_boundary;
        if (geoBoundary) {
            ogrid.Event.raise(ogrid.Event.types.REFRESH_DATA, {
                resultSetId: ogrid.guid(),
                data: geoBoundary,
                options: { clear: false, passthroughData: {} }
            });
        }

        // Auto-fit the map to the results extent.
        // Point features: collect lat/lon scalars and derive a bounding box.
        // Polygon features (boundary layers): delegate to Leaflet's own bounds
        // calculation, since coordinates are nested rings, not scalars.
        var me = this;
        var didFitBounds = false;
        if (results.features && results.features.length > 0) {
            try {
                var firstGeom = results.features[0] && results.features[0].geometry;
                var isPolygon = firstGeom && firstGeom.type !== 'Point' && firstGeom.type !== 'MultiPoint';

                if (isPolygon) {
                    // Pure boundary response — let Leaflet compute bounds from geometry
                    ogrid.App.map().getMap().fitBounds(
                        L.geoJSON(results).getBounds(), { padding: [40, 40] }
                    );
                    didFitBounds = true;
                } else {
                    // Point data — accumulate scalars across main results and any anchor layer
                    var lats = [], lons = [];
                    var collectCoords = function(fc) {
                        if (!fc || !fc.features) return;
                        $.each(fc.features, function(i, f) {
                            if (f.geometry && f.geometry.coordinates) {
                                lons.push(f.geometry.coordinates[0]);
                                lats.push(f.geometry.coordinates[1]);
                            }
                        });
                    };
                    collectCoords(results);
                    if (prox && prox.layer) { collectCoords(prox.layer); }
                    if (lats.length > 0) {
                        var sw = [Math.min.apply(null, lats), Math.min.apply(null, lons)];
                        var ne = [Math.max.apply(null, lats), Math.max.apply(null, lons)];
                        ogrid.App.map().getMap().fitBounds([sw, ne], { padding: [40, 40] });
                        didFitBounds = true;
                    }
                }
            } catch(e) {}
        }

        // Defer the "Search this area" watcher until after any auto-zoom animation
        if (didFitBounds) {
            try {
                ogrid.App.map().getMap().once('moveend', function() {
                    me._watchMapForSearchAgain();
                });
            } catch(e) {
                me._watchMapForSearchAgain();
            }
        } else {
            me._watchMapForSearchAgain();
        }
    },

    _watchMapForSearchAgain: function() {
        var me = this;
        try {
            var map = ogrid.App.map().getMap();
            if (me._mapMoveHandler) {
                map.off('moveend', me._mapMoveHandler);
            }
            $('#ogrid-search-again').hide();
            me._mapMoveHandler = function() {
                $('#ogrid-search-again').show();
            };
            map.on('moveend', me._mapMoveHandler);
        } catch(e) {}
    },

    _onExecError: function (err, rawErrorData, passThroughData) {
        var rd = rawErrorData || {};
        if (rd.txtStatus === 'timeout') {
            ogrid.Alert.error('Quick search has timed out.');
        } else {
            var msg = (rd.jqXHR && rd.jqXHR.responseText) ? rd.jqXHR.responseText : (typeof err === 'string' ? err : rd.txtStatus);
            ogrid.Alert.error(msg || 'An error occurred during search.');
        }
    },


    //public methods
    //call back for map extent change, invoked by map component
    regenerate: function(done) {
        console.log("Quick search - regenerate called");
        //re-invoke submit, passing along done callback
        this._onSearch(done);
    }

});
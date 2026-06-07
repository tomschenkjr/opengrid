/*
 * ogrid.Sidebar
 *
 * Icon-rail navigation: hamburger collapse + section switching.
 * Only "search" is functional; the other three show a placeholder.
 */
ogrid.Sidebar = ogrid.Class.extend({

    _sections: {
        place:    { icon: 'fa-map-marker', title: 'Place Profile' },
        trends:   { icon: 'fa-bar-chart',  title: 'Community Trends' },
        announce: { icon: 'fa-calendar',   title: 'Announcements & Events' }
    },

    init: function() {
        var me = this;

        $('#ogrid-hamburger').on('click', function() {
            $('#ogrid-sidebar').toggleClass('expanded');
        });

        $('#ogrid-sidebar .ogrid-nav-item').on('click', function(e) {
            e.preventDefault();
            var section = $(this).data('section');
            $('#ogrid-sidebar .ogrid-nav-item').removeClass('active');
            $(this).addClass('active');
            me._showSection(section);
        });
    },

    _showSection: function(section) {
        var $ph = $('#ogrid-section-placeholder');
        if (section === 'search') {
            $('#ogrid-container').removeClass('viewing-section');
            $ph.addClass('hide');
            return;
        }
        var cfg = this._sections[section] || { icon: 'fa-info-circle', title: section };
        $('#ogrid-container').addClass('viewing-section');
        $ph.html(
            '<div class="ph-icon"><i class="fa ' + cfg.icon + '"></i></div>' +
            '<div class="ph-title">' + cfg.title + '</div>' +
            '<div class="ph-sub">Coming soon.</div>'
        ).removeClass('hide');
    }
});

ogrid.sidebar = function() { return new ogrid.Sidebar(); };

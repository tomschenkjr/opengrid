/*
 * ogrid.Sidebar
 *
 * Icon-rail navigation: hamburger collapse + section switching.
 * Map, Community Trends, and Announcements & Events are addressable app pages.
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
            if (ogrid.App && ogrid.App.navigateToPage) {
                ogrid.App.navigateToPage(section);
            } else {
                me.showSection(section);
            }
        });
    },

    showSection: function(section, options) {
        options = options || {};
        var $ph = $('#ogrid-section-placeholder');
        var $cp = $('#ogrid-community-profile');
        var $ann = $('#ogrid-announcements-page');

        $('#ogrid-sidebar .ogrid-nav-item')
            .removeClass('active')
            .filter('[data-section="' + section + '"]')
            .addClass('active');

        $('#ogrid-clear-data-btn').toggle(section === 'search');

        if (section === 'search') {
            $('#ogrid-container').removeClass('viewing-section viewing-community-trends viewing-announcements');
            $ph.addClass('hide');
            $cp.addClass('hide');
            $ann.addClass('hide');
            ogrid.communityProfile().hide();
            if (ogrid.announcementsPage) { ogrid.announcementsPage().hide(); }
            return;
        }
        $('#ogrid-container')
            .addClass('viewing-section')
            .toggleClass('viewing-community-trends', section === 'trends')
            .toggleClass('viewing-announcements', section === 'announce');

        if (section === 'trends') {
            $ph.addClass('hide');
            $ann.addClass('hide');
            if (ogrid.announcementsPage) { ogrid.announcementsPage().hide(); }
            ogrid.communityProfile().show();
            if (options.communityArea) {
                ogrid.communityProfile().load(options.communityArea);
            }
            return;
        }

        $cp.addClass('hide');
        ogrid.communityProfile().hide();
        if (section === 'announce' && ogrid.announcementsPage) {
            $ph.addClass('hide');
            ogrid.announcementsPage().show(options);
            return;
        }
        $ann.addClass('hide');
        if (ogrid.announcementsPage) { ogrid.announcementsPage().hide(); }
        var cfg = this._sections[section] || { icon: 'fa-info-circle', title: section };
        $ph.html(
            '<div class="ph-icon"><i class="fa ' + cfg.icon + '"></i></div>' +
            '<div class="ph-title">' + cfg.title + '</div>' +
            '<div class="ph-sub">Coming soon.</div>'
        ).removeClass('hide');
    }
});

ogrid.sidebar = function() { return new ogrid.Sidebar(); };

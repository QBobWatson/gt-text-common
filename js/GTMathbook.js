/*******************************************************************************
 * GTMathbook.js
 *******************************************************************************
 * The main front-end controller for GT Mathbook documents.
 *
 * Rewritten by Joseph Rabinoff.
 *
 * Original Authors: Michael DuBois, David Farmer, Rob Beezer
 *
 *******************************************************************************
 */

// Leading semicolon safeguards against errors in script concatenation
// Pass dependencies into this closure from the bottom of the file
;(function($, w) {
    'use strict'; // Use EMCAScript 5 strict mode within this closure

    // This class handles two things:
    //  (1) Resizing the nav dropdown and content relative to the viewport.
    //  (2) Toggling the nav dropdown.
    // In full-page mode, (2) shows a drop-down menu.  In mobile mode, (2)
    // replaces the page content with the menu; this allows for much easier
    // scrolling on mobile browsers.

    var Mathbook = function() {
        var $dropdown = $(".dropdown");
        var $tocContents = $(".toc-contents");
        var $tocBorder = $(".toc-border-container");
        var $toggle = $(".toggle-button");
        var sectionId = $("section").first().attr("id");
        var $sectionLink = $("a[data-scroll=" + sectionId + "]");
        var $topLink = $(".toc-contents h2.link").first();
        var $bottomButtons = $(".navbar-bottom-buttons");
        var $navbar = $("#gt-navbar");
        var $content = $("#content");
        var $main = $("main.main").first();
        var $w = $(w);
        var firstShow = true;

        var topNav = function() {
            return $bottomButtons.css("display") === "none";
        }

        var hideDropdown = function(e) {
            $tocBorder.hide();
            $toggle.removeClass("active");
            $content.show();
            if(topNav()) {
                $dropdown.append($tocBorder);
            } else {
                $main.prepend($tocBorder);
            }
        }

        var showDropdown = function(resizeOnly) {
            $toggle.addClass("active");
            if(topNav()) {
                $content.show();
                $dropdown.append($tocBorder);
            } else {
                $content.hide();
                $main.prepend($tocBorder);
            }
            $tocBorder.show();
            if(firstShow) {
                // MathJax has no idea how big hidden elements will be
                MathJax.Hub.Queue(["Reprocess",MathJax.Hub,$tocBorder[0]]);
                firstShow = false;
            }
            // Mobile browsers resize often based on which UI elements are
            // present.  We don't want to re-scroll every time.
            if(resizeOnly) {return}
            if(topNav()) {
                $tocContents.animate({
                    scrollTop: ($sectionLink.position().top
                                - $tocContents.height()/2
                                + $sectionLink.outerHeight(true)/2
                                - $topLink.position().top) + 'px'
                }, 'fast');
            } else {
                $("body").animate({
                    scrollTop: ($sectionLink.offset().top
                                + $sectionLink.outerHeight(true)
                                + $navbar.outerHeight(true)/2
                                - $w.height()/2) + 'px'
                }, 'fast');
            }
        }

        var toggleDropdown = function(e) {
            if($toggle.hasClass("active")) {
                hideDropdown();
            } else {
                showDropdown();
            }
        }

        var updateDropdown = function(resizeOnly) {
            if($toggle.hasClass("active")) {
                showDropdown(resizeOnly);
            } else {
                hideDropdown();
            }
        }

        var hideDropdownMaybe = function(e) {
            if(!e.target.matches(".dropdown") &&
               !e.target.matches(".toggle-button") &&
               $toggle.hasClass("active")) {
                hideDropdown();
            }
        }

        var tocHeight = function() {
            return ($w.height()
                    - $dropdown.offset().top + $(document).scrollTop()
                    - $tocBorder.outerHeight(true) + $tocBorder.innerHeight())
                * .85;
        }

        var resize = function(e) {
            // Stick or unstick the navbar based on it is at the top or bottom.
            // This avoids needing to reduntantly define the media sizes in JS.
            if(topNav()) {
                // Navbar at the top
                if(!$navbar.parent(".sticky-wrapper").length) {
                    $navbar.sticky();
                }
                $navbar.sticky("update");

                // Set the height of the ToC
                $tocContents.css({maxHeight: tocHeight()});
            } else {
                $navbar.unstick();
                $tocContents.css({maxHeight: 'none'});
                /*
                // Set the height of the ToC
                $tocContents.css({
                    maxHeight: $dropdown.offset().top
                        - $tocBorder.outerHeight(true)
                        + $tocBorder.innerHeight()
                });
                */
            }

            updateDropdown(true);

            // Make sure the content is large enough to vertically fill the
            // window.
            $content.css({
                minHeight: $w.height()
                    - ($("body").innerHeight() - $content.innerHeight())
            });
        }

        var onScroll = function(e) {
            if(topNav()) {
                // Set the height of the ToC (which may have changed)
                $tocContents.css({maxHeight: tocHeight()});
            }
        }

        $toggle.on("click", toggleDropdown);
        $w.on("click", hideDropdownMaybe);
        $w.on("resize", resize);
        $w.scroll(onScroll);
        resize();

        // Hack
        if(!$("#toc a.active").length) {
            $("#toc h2.active a").addClass("active");
        }

        $(".mathbook-content section.hidden-subsection > header > h1").on(
            'click', function() {
                var parent = $(this).parent().parent();
                var child = parent.children(".hidden-subsection-content");
                if(parent.hasClass("active")) {
                    parent.removeClass("active");
                } else {
                    parent.addClass("active");
                }
                child.slideToggle(500);
            });
    };

    // If script is run after page is loaded, initialize immediately
    if(document.readyState === "complete") {
        w.mathbook = new Mathbook();
    } else {
        // wait and init when the DOM is fully loaded
        $(window).load( function() {
            w.mathbook = new Mathbook();
        });
    }

    // MathJax is now precompiled, but knowl.js doesn't know that.
    w.MathJax = {Hub: {Queue: function(cmd) {
        if(cmd[0] instanceof Function) {
            cmd[0]();
        }
    }}};

    return Mathbook;

})(jQuery, window);

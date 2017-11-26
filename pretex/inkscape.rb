class Inkscape < Formula
  desc "Professional vector graphics editor"
  homepage "https://inkscape.org/"
  url "https://launchpad.net/inkscape/0.92.x/0.92.2/+download/inkscape-0.92.2.tar.bz2"
  mirror "https://mirrors.kernel.org/debian/pool/main/i/inkscape/inkscape_0.92.2.orig.tar.bz2"
  sha256 "a628d0e04c254e9840947e6d866974f92c68ae31631a38b94d9b65e5cd84cfd3"
  revision 1

  head do
    url "https://gitlab.com/inkscape/inkscape.git", :using => :git
    url "https://gitlab.com/inkscape/inkscape.git", :using => :git, :branch => "0.92.x" if build.include? "branch-0.92"
  end

  stable do
    patch do
      url "https://gitlab.com/inkscape/inkscape/commit/93ccf03162cd2e46d962822d5507865f3451168c.diff"
      sha256 "1f037cc29cee8e0c60ab4753d4151741c8170e4849129bac68fdc60925eb971d"
    end
    patch :DATA
  end

  option "branch-0.92", "When used with --HEAD, build from the 0.92.x branch"

  option "with-gtk3", "Build Inkscape with GTK+3 (Experimental)"

  depends_on "automake" => :build
  depends_on "cmake" => :build
  depends_on "libtool" => :build
  depends_on "boost-build" => :build
  depends_on "intltool" => :build
  depends_on "pkg-config" => :build
  depends_on "bdw-gc"
  depends_on "boost"
  depends_on "cairomm"
  depends_on "gettext"
  depends_on "glibmm"
  depends_on "gsl"
  depends_on "hicolor-icon-theme"
  depends_on "libsoup" # > 0.92.x
  depends_on "little-cms"
  depends_on "pango"
  depends_on "popt"
  depends_on "poppler"
  depends_on "potrace"

  depends_on "gtkmm3" if build.with? "gtk3"
  depends_on "gdl" if build.with? "gtk3"
  depends_on "gtkmm" if build.without? "gtk3"

  needs :cxx11

  if MacOS.version < :mavericks
    fails_with :clang do
      cause "inkscape's dependencies will be built with libstdc++ and fail to link."
    end
  end

  def install
    ENV.cxx11
    ENV.append "LDFLAGS", "-liconv"

    system "mkdir", "build"
    Dir.chdir("build")
    system "cmake", "..", *std_cmake_args
    system "make"
    system "make", "install"
  end

  test do
    system "#{bin}/inkscape", "-x"
  end
end

__END__
diff -Naur a/src/extension/internal/pdfinput/pdf-input.cpp b/src/extension/internal/pdfinput/pdf-input.cpp
--- a/src/extension/internal/pdfinput/pdf-input.cpp	2017-02-13 18:46:57.000000000 -0500
+++ b/src/extension/internal/pdfinput/pdf-input.cpp	2017-11-26 17:04:34.473095657 -0500
@@ -768,6 +768,8 @@
         is_importvia_poppler = dlg->getImportMethod();
         // printf("PDF import via %s.\n", is_importvia_poppler ? "poppler" : "native");
 #endif
+    } else { // JDR
+        page_num = INKSCAPE.pdf_page;
     }
 
     SPDocument *doc = NULL;
diff -Naur a/src/extension/internal/pdfinput/svg-builder.cpp b/src/extension/internal/pdfinput/svg-builder.cpp
--- a/src/extension/internal/pdfinput/svg-builder.cpp	2017-02-13 18:46:57.000000000 -0500
+++ b/src/extension/internal/pdfinput/svg-builder.cpp	2017-11-26 17:12:23.183242531 -0500
@@ -89,7 +89,7 @@
 
     // Set default preference settings
     _preferences = _xml_doc->createElement("svgbuilder:prefs");
-    _preferences->setAttribute("embedImages", "1");
+    _preferences->setAttribute("embedImages", "0"); // JDR: changed default
     _preferences->setAttribute("localFonts", "1");
 }
 
@@ -1024,6 +1024,7 @@
     } else {
         _font_specification = (char*) "Arial";
     }
+    char *orig = _font_specification; // JDR
 
     // Prune the font name to get the correct font family name
     // In a PDF font names can look like this: IONIPB+MetaPlusBold-Italic
@@ -1032,6 +1033,7 @@
     char *font_style_lowercase = NULL;
     char *plus_sign = strstr(_font_specification, "+");
     if (plus_sign) {
+        *plus_sign = ' '; // JDR
         font_family = g_strdup(plus_sign + 1);
         _font_specification = plus_sign + 1;
     } else {
@@ -1045,6 +1047,7 @@
         style_delim[0] = 0;
     }
 
+#if 0 // JDR
     // Font family
     if (font->getFamily()) { // if font family is explicitly given use it.
         sp_repr_css_set_property(_font_style, "font-family", font->getFamily()->getCString());
@@ -1058,6 +1061,8 @@
             sp_repr_css_set_property(_font_style, "font-family", font_family);
         }
     }
+#endif // JDR
+    sp_repr_css_set_property(_font_style, "font-family", orig); // JDR
 
     // Font style
     if (font->isItalic()) {
@@ -1316,8 +1321,9 @@
 
                 // Set style and unref SPCSSAttr if it won't be needed anymore
                 // assume all <tspan> nodes in a <text> node share the same style
-                sp_repr_css_change(text_node, glyph.style, "style");
-                if ( glyph.style_changed && i != _glyphs.begin() ) {    // Free previous style
+                // JDR: this is a bad assumption.  Don't do that.
+                sp_repr_css_change(tspan_node, glyph.style, "style");
+                if ( glyph.style_changed && i != _glyphs.begin() && 0 ) {    // Free previous style
                     sp_repr_css_attr_unref((*prev_iterator).style);
                 }
             }
@@ -1507,7 +1513,7 @@
         return NULL;
     }
     // Decide whether we should embed this image
-    int attr_value = 1;
+    int attr_value = 0;
     sp_repr_get_int(_preferences, "embedImages", &attr_value);
     bool embed_image = ( attr_value != 0 );
     // Set read/write functions
diff -Naur a/src/inkscape.h b/src/inkscape.h
--- a/src/inkscape.h	2017-02-13 18:46:57.000000000 -0500
+++ b/src/inkscape.h	2017-11-26 17:04:34.477095640 -0500
@@ -195,6 +195,8 @@
     // may not be reflected by a selection change and thus needs a separate signal
     sigc::signal<void> signal_external_change;
 
+    gint pdf_page;  // JDR
+
 private:
     static Inkscape::Application * _S_inst;
 
diff -Naur a/src/main.cpp b/src/main.cpp
--- a/src/main.cpp	2017-02-13 18:46:57.000000000 -0500
+++ b/src/main.cpp	2017-11-26 17:04:34.477095640 -0500
@@ -167,6 +167,7 @@
     SP_ARG_EXPORT_WMF,
     SP_ARG_EXPORT_TEXT_TO_PATH,
     SP_ARG_EXPORT_IGNORE_FILTERS,
+    SP_ARG_PDF_PAGE, // JDR
     SP_ARG_EXTENSIONDIR,
     SP_ARG_QUERY_X,
     SP_ARG_QUERY_Y,
@@ -226,6 +227,7 @@
 static gboolean sp_export_text_to_path = FALSE;
 static gboolean sp_export_ignore_filters = FALSE;
 static gboolean sp_export_font = FALSE;
+static gint sp_pdf_page = 1; // JDR
 static gboolean sp_query_x = FALSE;
 static gboolean sp_query_y = FALSE;
 static gboolean sp_query_width = FALSE;
@@ -273,6 +275,7 @@
         sp_export_text_to_path = FALSE;
         sp_export_ignore_filters = FALSE;
         sp_export_font = FALSE;
+        sp_pdf_page = 1;
         sp_query_x = FALSE;
         sp_query_y = FALSE;
         sp_query_width = FALSE;
@@ -450,6 +453,12 @@
      N_("Render filtered objects without filters, instead of rasterizing (PS, EPS, PDF)"),
      NULL},
 
+    // JDR
+    {"pdf-page", 0,
+     POPT_ARG_INT, &sp_pdf_page, SP_ARG_PDF_PAGE,
+     N_("PDF page to import"),
+     N_("PAGE")},
+
     {"query-x", 'X',
      POPT_ARG_NONE, &sp_query_x, SP_ARG_QUERY_X,
      // TRANSLATORS: "--query-id" is an Inkscape command line option; see "inkscape --help"
@@ -1135,6 +1144,7 @@
 
     /// \todo FIXME BROKEN - non-UTF-8 sneaks in here.
     Inkscape::Application::create(argv[0], true);
+    INKSCAPE.pdf_page = sp_pdf_page; // JDR
 
     while (fl) {
         if (sp_file_open((gchar *)fl->data,NULL)) {
@@ -1355,6 +1365,7 @@
                         poptSetOtherOptionHelp(ctx, _("[OPTIONS...] [FILE...]\n\nAvailable options:"));
                         if ( ctx ) {
                             GSList *fl = sp_process_args(ctx);
+                            INKSCAPE.pdf_page = sp_pdf_page; // JDR
                             if (sp_process_file_list(fl)) {
                                 retval = -1;
                             }
@@ -1408,6 +1419,7 @@
     }
 
     Inkscape::Application::create(argv[0], false);
+    INKSCAPE.pdf_page = sp_pdf_page; // JDR
 
     if (sp_shell) {
         int retVal = sp_main_shell(argv[0]); // Run as interactive shell

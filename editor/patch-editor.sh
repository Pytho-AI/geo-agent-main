#!/bin/sh
# Patch editor container to disable feedback/welcome dialogs.
# Runs as root to patch, then drops to cool user for coolwsd.
F="/usr/share/coolwsd/browser/dist/global.js"
sed -i \
  -e 's/window\.autoShowFeedback=true/window.autoShowFeedback=false/g' \
  -e 's/window\.autoShowWelcome=true/window.autoShowWelcome=false/g' \
  -e 's/window\.enableWelcomeMessage=true/window.enableWelcomeMessage=false/g' \
  -e "s/window\.autoShowFeedback=element\.dataset\.autoShowFeedback\.toLowerCase()\.trim()===\"true\"/window.autoShowFeedback=false/g" \
  -e "s/window\.autoShowWelcome=element\.dataset\.autoShowWelcome\.toLowerCase()\.trim()===\"true\"/window.autoShowWelcome=false/g" \
  -e "s/window\.enableWelcomeMessage=element\.dataset\.enableWelcomeMessage\.toLowerCase()\.trim()===\"true\"/window.enableWelcomeMessage=false/g" \
  -e "s/window\.allowUpdateNotification=element\.dataset\.allowUpdateNotification\.toLowerCase()\.trim()===\"true\"/window.allowUpdateNotification=false/g" \
  "$F"
# Fix WebSocket onmessage crash: event.data.startsWith() fails on binary messages
# (Blob/ArrayBuffer). Add type guard so it only calls startsWith on strings.
sed -i 's/global\.socket\.onmessage=function(event){if(event\.data\.startsWith/global.socket.onmessage=function(event){if(typeof event.data==="string"\&\&event.data.startsWith/' "$F"
echo "[patch-editor] Fixed WebSocket onmessage startsWith type guard"
# NUCLEAR: Replace the entire Feedback handler class with a dead stub using awk.
# bundle.js is one giant line — sed can't do multi-pattern on it reliably. awk can.
B="/usr/share/coolwsd/browser/dist/bundle.js"
awk '{
  # Replace the entire Feedback class + its init hook with a dead stub
  gsub(/window\.L\.Map\.Feedback=window\.L\.Handler\.extend\(\{[^}]*addHooks:function\(\)\{[^}]*\}[^}]*removeHooks:function\(\)\{[^}]*\}[^}]*removeIframe:function\(\)\{[^}]*\}/, "window.L.Map.Feedback=window.L.Handler.extend({addHooks:function(){},removeHooks:function(){},removeIframe:function(){}")
  # Kill feedback map option so the handler is never enabled
  gsub(/feedback:!window\.ThisIsAMobileApp/, "feedback:false")
  # Kill feedbackUrl and buyProductUrl guards
  gsub(/window\.feedbackUrl&&window\.prefs\.canPersist/, "false")
  gsub(/customWindow\.feedbackUrl&&customWindow\.buyProductUrl/, "false")
  # Kill showInfoBar (community edition nag)
  gsub(/UIManager\.prototype\.showInfoBar=function\(e\)\{/, "UIManager.prototype.showInfoBar=function(e){return;")
  # Kill the docCount>15 feedback trigger
  gsub(/docCount>15&&currentDate>laterDate&&window\.autoShowFeedback/, "false")
  # Kill onFeedback
  gsub(/onFeedback:function\(\)\{if\(/, "onFeedback:function(){return;if(")
  # Kill askForFeedbackDialog
  gsub(/askForFeedbackDialog:function\(\)\{/, "askForFeedbackDialog:function(){return;")
  # Kill showFeedbackDialog
  gsub(/showFeedbackDialog:function\(\)\{if\(/, "showFeedbackDialog:function(){return;if(")
  # Delete the literal snackbar text
  gsub(/Please send us your feedback/, "")
  # Kill the feedback menu item click handler
  gsub(/this\._map\.feedback\.showFeedbackDialog\(\)/, "void 0")
  # Kill _createFileIcon (menubar Collabora logo) — return immediately
  gsub(/Menubar\.prototype\._createFileIcon=function\(\)\{/, "Menubar.prototype._createFileIcon=function(){return;")
  # Kill _checkItemVisibility for help menu — return false when id is "help"
  gsub(/Menubar\.prototype\._checkItemVisibility=function\(menuItem\)\{/, "Menubar.prototype._checkItemVisibility=function(menuItem){if(menuItem.id===\"help\")return false;")
  print
}' "$B" > "${B}.tmp" && mv "${B}.tmp" "$B"
# Kill Help tab + menu with sed (awk can't handle literal parens in these patterns)
sed -i 's/,this\.getHelpTab()//g' "$B"
sed -i 's/this\.getHelpTab(),//g' "$B"
sed -i 's/this\.getHelpTab()//g' "$B"
# Kill ALL Help tab headers from notebookbar getTabs() arrays.
# bundle.js may have newlines (from original formatting), so slurp entire file.
awk 'BEGIN{RS="\x01"; ORS=""} {
  # Remove Help tab header objects — [^}]* skips over inner accessibility:{...}
  while (match($0, /,[[:space:]]*\{[[:space:]]*id:"Help-tab-label"[^}]*\{[^}]*\}[[:space:]]*\}/)) {
    $0 = substr($0, 1, RSTART-1) substr($0, RSTART+RLENGTH)
  }
  # Variable-based: ,{text:_("Help"),id:helpTabName+"-tab-label"...}}
  while (match($0, /,[[:space:]]*\{[[:space:]]*text:_\([[:space:]]*"Help"\),id:helpTabName[^}]*\{[^}]*\}[[:space:]]*\}/)) {
    $0 = substr($0, 1, RSTART-1) substr($0, RSTART+RLENGTH)
  }
  print
}' "$B" > "${B}.tmp" && mv "${B}.tmp" "$B"
# Kill getHelpTab function definition so it returns nothing
sed -i 's/getHelpTab:function(){/getHelpTab:function(){return {};/g' "$B"
# Kill the Help content page builder (helpTabName variable approach)
sed -i 's/var helpTabName="Help"/var helpTabName="DISABLED_HELP"/g' "$B"
# _fitWidthZoom is Impress's native slide-to-viewport fit. Previously
# stubbed globally to suppress Writer's 170%-on-wide-screen zoom, which
# also disabled Impress's fit and produced the title-clipped-off-the-
# right-edge bug for PPTX with the chat column open. Restored to native
# behavior — Impress fits the slide, Writer's wide-screen zoom is a
# separate non-critical issue.
# Force classic (single-toolbar / "compact") UI mode for initial render
# regardless of localStorage state, uiDefaults, or per-doctype prefs.
# Empirically: setting localStorage.compactMode='true' via global.js was
# unreliable — Impress kept opening in notebookbar even with the pref
# written before bundle.js init. The bundle has multiple call sites that
# read shouldUseNotebookbarMode() and at least one of them was reaching
# it before our localStorage was queried.
# Direct stub: shouldUseNotebookbarMode always returns false. This pins
# initial UI to classic for ALL doctypes (Writer/Impress/Calc). The
# runtime fullscreen toggle is unaffected — it postMessages
# Action_ChangeUIMode{Mode:"notebookbar"} which lands in onChangeUIMode
# directly; that function sets the mode by calling removeClassicUI() +
# addNotebookbarUI() without consulting shouldUseNotebookbarMode. Exit-
# fullscreen postMessages {Mode:"classic"} and gets the inverse. So:
# - Initial windowed iframe load → classic (always).
# - User clicks fullscreen → ribbon.
# - User exits fullscreen → classic.
# - Next iframe load (refresh / re-open) → classic again.
# Prefix-replace trick: insert a return-false stub before the original
# definition under a renamed identifier. Same pattern as _fitWidthZoom
# above. Avoids multi-line sed because the bundle's minified function
# body spans multiple lines and `[^}]*` doesn't cross newlines in default
# sed mode.
#   Before: shouldUseNotebookbarMode=function(){var forceCompact=...}
#   After:  shouldUseNotebookbarMode=function(){return false},
#           _shouldUseNotebookbarMode_orig=function(){var forceCompact=...}
# The comma-expression form is valid JS — left assignment pins the real
# property to the stub, right assignment creates a global var holding
# the original (kept around for forensics, never called).
sed -i 's/shouldUseNotebookbarMode=function/shouldUseNotebookbarMode=function(){return false},_shouldUseNotebookbarMode_orig=function/' "$B"
echo "[patch-editor] shouldUseNotebookbarMode stubbed: $(grep -c '_shouldUseNotebookbarMode_orig' "$B")"
# Prevent sidebar from opening on document load.
# Root cause: initializeSidebar() in Control.UIManager.ts reads
# getBooleanDocTypePref('ShowSidebar', true) — defaults to true — then
# sends 'uno .uno:SidebarShow' which opens the PropertyDeck panel.
# Stub it the same way as _fitWidthZoom: no-op before the real definition.
# Bundle uses prototype assignment: initializeSidebar=function(){if(...
sed -i 's/initializeSidebar=function/initializeSidebar=function(){},_initializeSidebar_orig=function/' "$B"
echo "[patch-editor] Disabled sidebar on load"
echo "[patch-editor] initializeSidebar stubbed: $(grep -c '_initializeSidebar_orig' "$B")"
# Fix notebookbar font combobox — only shows "Carlito" instead of all fonts.
# Root cause: fontnamecombobox is forced through _listboxControl (static entries)
# instead of _comboboxControl (JSDialog.combobox with updateEntries method).
# Fix: Remove fontnamecombobox from shouldBeListbox so it renders as JSDialog.combobox.
# The editor's native font selection mechanism handles everything else.
sed -i 's/data.id==="applystyle"||data.id==="fontnamecombobox"||data.id==="fontsizecombobox"/data.id==="applystyle"||data.id==="fontsizecombobox"/' "$B"
echo "[patch-editor] fontnamecombobox removed from shouldBeListbox"
# Populate font list and sync current font display via global.js injection.
cat >> "$F" << 'FONTPATCH'
/* ── Force compact (single-toolbar) UI on every initial iframe load ──
   The relevant preference Collabora's UIManager reads at startup is
   `compactMode` (boolean string). From browser/js/global.js prefs.get:
       const forceCompact = window.prefs.get('compactMode', null);
       const shouldUseClassic = (window.userInterfaceMode === 'classic' &&
           forceCompact == null) || forceCompact === 'true';
       return !shouldUseClassic;   // ← notebookbar (ribbon) if not classic
   prefs.get() reads from localStorage when no uiDefaults override is
   present, so writing `compactMode='true'` synchronously before
   UIManager initializes pins the doc to single-toolbar layout for ALL
   doctypes (Writer / Impress / Calc). The fullscreen toggle still flips
   to notebookbar at runtime via Action_ChangeUIMode (which calls
   onChangeUIMode → prefs.set('compactMode', false)); exiting fullscreen
   posts another Action_ChangeUIMode that flips back. On the NEXT iframe
   load this override runs again and reverts any persisted false value,
   so windowed-mode is always single-toolbar even after the user has
   used fullscreen during the prior session. */
(function(){
  try {
    localStorage.setItem('compactMode', 'true');
  } catch(e) {}
})();
/* ── Auto dark mode from system preference ── */
(function(){
  try {
    var key = 'darkTheme';
    var stored = localStorage.getItem(key);
    if (stored === null && window.matchMedia) {
      var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (prefersDark) {
        localStorage.setItem(key, 'true');
        document.documentElement.setAttribute('data-theme', 'dark');
      }
    }
    /* When dark mode is active, force inverted background (white page)
       so the document looks normal instead of jarring dark canvas. */
    if (localStorage.getItem('darkTheme') === 'true') {
      localStorage.setItem('darkBackgroundForTheme.dark', 'false');
    }
  } catch(e) {}
})();
/* ── Populate font combobox with server font list ── */
/* Root cause: JSDialog's combobox/listbox only shows entries from the server
   message — which contains only the current font (e.g. Carlito), not all fonts.
   Fix: create a real <select>, hide the JSDialog combobox, and use the map's
   built-in createFontSelector (select2) to populate it with the full font list. */
(function(){
  function getMap(){return window.L&&window.L.Map&&window.L.Map.THIS||null;}
  var _fi=setInterval(function(){
    var m=getMap();
    if(!m)return;
    var orig=document.getElementById('fontnamecombobox');
    if(!orig)return;
    clearInterval(_fi);
    /* Create a real <select> that createFontSelector can populate */
    var sel=document.createElement('select');
    sel.id='pytho-font-selector';
    sel.style.width='150px';
    sel.style.height='24px';
    sel.style.fontSize='12px';
    orig.parentNode.insertBefore(sel,orig);
    orig.style.display='none';
    m.createFontSelector('#pytho-font-selector');
  },500);
  setTimeout(function(){clearInterval(_fi);},30000);
})();
FONTPATCH
echo "[patch-editor] Injected font population code"
# Verify
echo "[patch-editor] Feedback text remaining: $(grep -c 'Please send us your feedback' "$B")"
echo "[patch-editor] _createFileIcon killed: $(grep -c '_createFileIcon=function(){return' "$B")"
echo "[patch-editor] getHelpTab calls remaining: $(grep -c 'this\.getHelpTab' "$B")"
echo "[patch-editor] Help-tab-label remaining: $(grep -c 'Help-tab-label' "$B")"
# Hide the empty Styles preview in notebookbar (Collabora bug — previews never render)
CSS="/usr/share/coolwsd/browser/dist/bundle.css"
echo '#home-stylesview-group { display: none !important; }' >> "$CSS"
# Fix horizontal overflow when sidebar is open — #document-container has width:100%
# but sits in a flex row with the sidebar, so total width exceeds viewport.
# min-width:0 lets flex-shrink actually work; overflow:hidden on the row prevents bleed.
echo '#document-container { min-width: 0 !important; }' >> "$CSS"
echo '#main-document-content { overflow: hidden !important; }' >> "$CSS"
echo "[patch-editor] Fixed sidebar horizontal overflow"
echo "[patch-editor] Hidden empty Styles preview"
# Remove .document-logo from the rule that adds background-color:#e9e9ed to toolbar buttons.
# The Pytho logo SVG is white wireframe on transparent — the button background shows through.
sed -i 's/\.document-logo,\.ui-tabs-content/\.ui-tabs-content/' "$CSS"
cat >> "$CSS" << 'BRANDCSS'
/* Kill the floating formatting popup on text selection */
#context-toolbar { display: none !important; }
/* Force document-logo background transparent — dark theme sets #1e293b */
#document-logo, .document-logo, a.document-logo { background-color: transparent !important; }
/* Match Pytho site toolbar color: rgb(2, 6, 23) */
.main-nav, .main-nav.hasnotebookbar { background-color: #020617 !important; }
/* Kill the "Collabora Online Development Edition (unbranded)" boot
   splash logo + brand label. The .leaflet-progress-spinner div hosts
   the canvas-drawn Collabora play-button logo; .brand-label hosts the
   product-name text. Hiding both leaves the "Initializing..." status
   text + progress bar visible so the analyst still sees a loading
   affordance — just without the Collabora branding the user does not
   want surfaced. Bundle.js also gets the fallback string sed'd to
   empty below as a belt-and-suspenders on any code path that reads
   the string directly instead of rendering through the splash. */
.leaflet-progress-spinner,
.leaflet-progress-label.brand-label { display: none !important; }
BRANDCSS
# Also kill the "Collabora Online Development Edition (unbranded)"
# fallback string in bundle.js for any code path that reads it via
# `typeof brandProductName !== "undefined" ? brandProductName : "..."`
# WITHOUT going through the splash element (e.g. About dialog title).
# 7 occurrences in bundle.js as of Collabora 25.04.9.
sed -i 's/Collabora Online Development Edition (unbranded)//g' "$B"
echo "[patch-editor] Suppressed Collabora boot splash branding"
# Kill "Writer" tooltip on document logo
sed -i 's/iconTooltip="Writer"/iconTooltip=""/g' "$B"
sed -i 's/iconTooltip="Calc"/iconTooltip=""/g' "$B"
sed -i 's/iconTooltip="Impress"/iconTooltip=""/g' "$B"
sed -i 's/iconTooltip="Draw"/iconTooltip=""/g' "$B"
# Kill branding.css rules that override .document-logo background with Collabora's logo SVG
BCSS="/usr/share/coolwsd/browser/dist/branding.css"
sed -i '/\.document-logo/d' "$BCSS"
# Override toolbar color to Pytho site color rgb(2,6,23) = #020617
sed -i 's/background-color: rgb(var(--doc-type, var(--co-primary-elment-rgb))) !important/background-color: #020617 !important/' "$BCSS"
echo "[patch-editor] Applied Pytho branding CSS"
# ── Install missing icons ──────────────────────────────────────────────────
# Some icons (lc_themedialog.svg, dark/pagewidth.svg) are missing from this
# container build but referenced by the UI. Copy from mounted directory.
IMGS="/usr/share/coolwsd/browser/dist/images"
if [ -d /editor-icons ]; then
  cp /editor-icons/*.svg "$IMGS/" 2>/dev/null
  cp /editor-icons/dark/*.svg "$IMGS/dark/" 2>/dev/null
  echo "[patch-editor] Installed missing editor icons"
fi
# Gut branding.js — it polls for #document-header and sets Collabora href/tooltip
echo '/* branding disabled */' > /usr/share/coolwsd/browser/dist/branding.js
# Replace the Writer file-type icon (x-office-document.svg) with the Pytho logo.
# This is the icon shown in the top-left corner of the notebookbar.
# No logoURL, no CSS overrides — just swap the file. Existing CSS handles sizing.
if [ -f /pytho-logo.svg ]; then
  cp /pytho-logo.svg "$IMGS/x-office-document.svg"
  echo "[patch-editor] Replaced writer icon with Pytho logo"
else
  echo "[patch-editor] WARNING: pytho-logo.svg not found"
fi
echo "[patch-editor] NUKED all feedback/welcome/infobar popups + logo button"

# ── Calc-specific UI suppressions ─────────────────────────────────────────
# bundle.js is shared across Writer / Calc / Impress so most of the above
# patches already apply when an XLSX document is loaded. The ones that
# DON'T apply uniformly are font-pickers (per-app widgets), sidebars
# (Calc has its own Properties + Functions panels), and the Calc-only
# "Replace text as you type" autocorrect prompt that pops on every cell.
#
# Mirror the autoShowFeedback / autoShowWelcome shutdown for Calc paths.
# Calc loads through the same global.js but registers its own
# applicationManager — explicit suppressions guard against per-app
# overrides Collabora may introduce in future image bumps.
sed -i \
  -e 's/window\.calcAutoCorrectAutoComplete=true/window.calcAutoCorrectAutoComplete=false/g' \
  -e 's/showcalcautocompletepopup=true/showcalcautocompletepopup=false/g' \
  "$F"
# Calc Functions panel default-open. Same mechanism as Writer's
# initializeSidebar but Calc has its own per-doctype default which a
# future image bump may pin to ShowSidebar=true. Belt + suspenders:
# also strip the .uno:SidebarShow call from the Calc init path.
sed -i 's/calcInitializeSidebar=function/calcInitializeSidebar=function(){},_calcInitializeSidebar_orig=function/' "$B" 2>/dev/null || true
echo "[patch-editor] Calc-specific UI suppressions applied"

# Mirror the Writer fontnamecombobox population code for Calc's
# font-name widget. The notebookbar in Calc mode shares the
# fontnamecombobox id when in same notebookbar layout, but if Calc
# uses a separate id (cell-font-name), the polling code below picks
# that up too without breaking Writer.
cat >> "$F" << 'CALCFONTPATCH'
/* ── Calc-side font selector population (sibling to the Writer block) ── */
(function(){
  function getMap(){return window.L&&window.L.Map&&window.L.Map.THIS||null;}
  var tries=0;
  var _ci=setInterval(function(){
    var m=getMap(); tries++;
    if(tries>60){clearInterval(_ci);return;}
    if(!m||m.getDocType&&m.getDocType()!=='spreadsheet')return;
    /* Calc may surface a different combobox id; try both. */
    var orig=document.getElementById('cell-font-name')||document.getElementById('fontnamecombobox');
    if(!orig||document.getElementById('pytho-calc-font-selector'))return;
    clearInterval(_ci);
    var sel=document.createElement('select');
    sel.id='pytho-calc-font-selector';
    sel.style.width='150px';
    sel.style.height='24px';
    sel.style.fontSize='12px';
    orig.parentNode.insertBefore(sel,orig);
    orig.style.display='none';
    try{m.createFontSelector('#pytho-calc-font-selector');}catch(e){}
  },500);
})();
CALCFONTPATCH
echo "[patch-editor] Calc font selector population injected"
# Install fonts: OpenSymbol (bullets), cabextract+wget (for MS core fonts download).
# Single apt-get call to avoid DNS cache issues between separate calls.
apt-get update -qq 2>&1 && apt-get install -y -qq fonts-opensymbol cabextract wget unzip 2>&1
echo "[patch-editor] Installed fonts-opensymbol + cabextract + wget"
# Install Microsoft core fonts (Arial, Times New Roman, etc.) via SourceForge download.
# ttf-mscorefonts-installer Debian package fails in this container (x11-common postinst
# needs /usr/share/debconf/frontend). We do what the package does: download cab files
# from SourceForge, extract with cabextract, install to the standard fonts dir.
# EULA: https://corefonts.sourceforge.net/eula.htm — accepted per project policy.
MSFONTS_DIR="/usr/share/fonts/truetype/msttcorefonts"
mkdir -p "$MSFONTS_DIR"
SF_URL="https://master.dl.sourceforge.net/project/corefonts/the%20fonts/final"
for cab in arial32.exe arialb32.exe comic32.exe courie32.exe georgi32.exe impact32.exe times32.exe trebuc32.exe verdan32.exe webdin32.exe; do
  wget -q -T 30 "$SF_URL/$cab" -O "/tmp/$cab" 2>/dev/null && \
    cabextract -q -d "$MSFONTS_DIR" "/tmp/$cab" 2>/dev/null && \
    rm -f "/tmp/$cab"
done
fc-cache -f 2>/dev/null
FONT_COUNT=$(find "$MSFONTS_DIR" -iname "*.ttf" 2>/dev/null | wc -l)
echo "[patch-editor] MS core fonts installed: $FONT_COUNT TTF files"
# CRITICAL: Collabora runs LibreOffice inside chroot jails from /opt/cool/systemplate/.
# The systemplate is built at image build time — fonts installed at runtime are NOT in it.
# Copy all new fonts into systemplate so jails pick them up.
SYSPLATE="/opt/cool/systemplate"
if [ -d "$MSFONTS_DIR" ] && [ "$FONT_COUNT" -gt 0 ]; then
  cp -r -p "$MSFONTS_DIR" "$SYSPLATE/usr/share/fonts/truetype/msttcorefonts"
fi
if [ -d /usr/share/fonts/truetype/openoffice ]; then
  cp -r -p /usr/share/fonts/truetype/openoffice "$SYSPLATE/usr/share/fonts/truetype/openoffice"
fi
FONTCONFIG_PATH="$SYSPLATE/etc/fonts" fc-cache -f -s "$SYSPLATE/usr/share/fonts" 2>/dev/null
echo "[patch-editor] Copied fonts into systemplate for jail visibility"

# Set default document font to Arial (instead of Cambria).
# Drop a custom XCD override into LO's registry — loaded after main.xcd.
REGISTRY="/opt/collaboraoffice/share/registry"
cat > "$REGISTRY/pytho-defaults.xcd" << 'FONTXCD'
<?xml version="1.0" encoding="UTF-8"?>
<oor:data xmlns:xs="http://www.w3.org/2001/XMLSchema"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xmlns:oor="http://openoffice.org/2001/registry">
  <dependency file="main"/>
  <!-- Writer defaults: all fonts → Arial, consistent sizing -->
  <oor:component-data oor:name="Writer" oor:package="org.openoffice.Office">
    <node oor:name="DefaultFont">
      <prop oor:name="Standard" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="StandardHeight" oor:op="fuse"><value>12</value></prop>
      <prop oor:name="Heading" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="HeadingHeight" oor:op="fuse"><value>16</value></prop>
      <prop oor:name="List" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="ListHeight" oor:op="fuse"><value>12</value></prop>
      <prop oor:name="Caption" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="CaptionHeight" oor:op="fuse"><value>10</value></prop>
      <prop oor:name="Index" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="IndexHeight" oor:op="fuse"><value>12</value></prop>
    </node>
    <node oor:name="DefaultFontCJK">
      <prop oor:name="Standard" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="StandardHeight" oor:op="fuse"><value>12</value></prop>
      <prop oor:name="Heading" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="HeadingHeight" oor:op="fuse"><value>16</value></prop>
    </node>
    <node oor:name="DefaultFontCTL">
      <prop oor:name="Standard" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="StandardHeight" oor:op="fuse"><value>12</value></prop>
      <prop oor:name="Heading" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="HeadingHeight" oor:op="fuse"><value>16</value></prop>
    </node>
  </oor:component-data>
  <!-- Measurement: inches (US standard) -->
  <oor:component-data oor:name="Writer" oor:package="org.openoffice.Office">
    <node oor:name="Layout">
      <node oor:name="Other">
        <prop oor:name="MeasureUnit" oor:op="fuse"><value>1</value></prop>
      </node>
    </node>
  </oor:component-data>
  <!-- Calc defaults: cell font Arial 10pt (matches the doctrinal XLSX
       exporter's openpyxl Font(name="Arial", size=10) so what the
       analyst types in a fresh cell matches the surrounding
       schema-generated cells). -->
  <oor:component-data oor:name="Calc" oor:package="org.openoffice.Office">
    <node oor:name="DefaultFont">
      <prop oor:name="Standard" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="StandardHeight" oor:op="fuse"><value>10</value></prop>
    </node>
    <node oor:name="DefaultFontCJK">
      <prop oor:name="Standard" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="StandardHeight" oor:op="fuse"><value>10</value></prop>
    </node>
    <node oor:name="DefaultFontCTL">
      <prop oor:name="Standard" oor:op="fuse"><value>Arial</value></prop>
      <prop oor:name="StandardHeight" oor:op="fuse"><value>10</value></prop>
    </node>
    <!-- Hide the autocomplete + autoinput dropdown which pops on every
         partial cell entry — disruptive in a doctrinal ledger where the
         analyst is filling in priority numbers, MGRS strings, enum
         values that should NOT auto-complete from the prior column. -->
    <node oor:name="Input">
      <prop oor:name="AutoInput" oor:op="fuse"><value>false</value></prop>
    </node>
  </oor:component-data>
  <!-- Icon theme: sukapura (modern macOS-style) -->
  <oor:component-data oor:name="Common" oor:package="org.openoffice.Office">
    <node oor:name="Misc">
      <prop oor:name="SymbolStyle" oor:op="fuse"><value>sukapura_svg</value></prop>
    </node>
  </oor:component-data>
</oor:data>
FONTXCD
# Install sukapura icon theme (modern macOS-style icons).
# Collabora's web UI serves icons from browser/dist/images/, NOT from LO icon theme zips.
# We overlay sukapura SVGs onto the existing dist/images/ directory — only replacing
# files that exist in both (634 of 1250). The rest keep Collabora's default look.
IMGS="/usr/share/coolwsd/browser/dist/images"
if [ -f /images_sukapura_svg.zip ]; then
  SUKA_TMP="/tmp/sukapura_extract"
  mkdir -p "$SUKA_TMP"
  unzip -q -o /images_sukapura_svg.zip -d "$SUKA_TMP"
  REPLACED=0
  # Skip icons where sukapura's version means something different than Collabora's.
  # minus.svg/plus.svg: sukapura = tree expand/collapse triangles, Collabora = zoom +/- buttons
  SKIP_ICONS="minus.svg plus.svg"
  find "$SUKA_TMP" -name "*.svg" | while read svg; do
    base=$(basename "$svg")
    skip=false
    for s in $SKIP_ICONS; do [ "$base" = "$s" ] && skip=true; done
    if [ "$skip" = "false" ] && [ -f "$IMGS/$base" ]; then
      cp "$svg" "$IMGS/$base"
    fi
  done
  # Count replacements for logging
  REPLACED=$(find "$SUKA_TMP" -name "*.svg" -exec basename {} \; | sort -u | while read b; do [ -f "$IMGS/$b" ] && echo x; done | wc -l)
  rm -rf "$SUKA_TMP"
  echo "[patch-editor] Replaced $REPLACED icons with sukapura theme"
fi
# Copy into systemplate so jails see it
cp "$REGISTRY/pytho-defaults.xcd" "$SYSPLATE/opt/collaboraoffice/share/registry/" 2>/dev/null
echo "[patch-editor] Set default font to Arial 12pt + sukapura icons"

# Enable macro execution and UNO Remote Protocol over WebSocket.
# This allows us to modify list styles (NumberingRules) at runtime to set
# military multilevel numbering (1. / a. / (1) / (a)).
CONF="/etc/coolwsd/coolwsd.xml"
sed -i \
  -e 's|<enable_macros_execution[^>]*>[^<]*</enable_macros_execution>|<enable_macros_execution desc="" type="bool" default="false">true</enable_macros_execution>|' \
  -e 's|<macro_security_level[^>]*>[^<]*</macro_security_level>|<macro_security_level desc="" type="int" default="1">0</macro_security_level>|' \
  -e 's|<enable_websocket_urp[^>]*>[^<]*</enable_websocket_urp>|<enable_websocket_urp desc="" type="bool" default="false">true</enable_websocket_urp>|' \
  "$CONF"
echo "[patch-editor] Enabled macros + WebSocket URP"

# Bump num_prespawn_children from the default 1 → 4. The forkit's LO
# library preload (~8 s on first container start) is paid once at
# boot. After that, each pre-spawned kit is a copy-on-write fork from
# the warm forkit and starts in milliseconds. With 1 pre-spawned kit
# (the default), opening 2 docs back-to-back means doc #2 waits for
# a fresh fork (~1 s) + Impress's eager slide-load on a cold kit
# (~3 s on a PPTX with embedded images). Bumping to 4 means 4 kits
# sit idle ready to grab; the first 4 simultaneous opens are
# instant. RAM cost is ~30 MB per idle kit — well within budget.
sed -i \
  -e 's|<num_prespawn_children[^>]*>[^<]*</num_prespawn_children>|<num_prespawn_children desc="Number of child processes to keep started in advance and waiting for new clients." type="uint" default="1">4</num_prespawn_children>|' \
  "$CONF"
echo "[patch-editor] num_prespawn_children=4 (was 1)"

# Install "Military" Basic macro library into LO's shared libraries.
# This macro configures "Numbering 1" list style with military outline levels:
# 1. / a. / (1) / (a) — called via .uno:RunMacro after document load.
BASIC_DIR="/opt/collaboraoffice/share/basic"
mkdir -p "$BASIC_DIR/Military"
cp /military_macro/Module1.xba "$BASIC_DIR/Military/"
cp /military_macro/script.xlb "$BASIC_DIR/Military/"
# Register in the global library catalog
sed -i '/<\/library:libraries>/i \
 <library:library library:name="Military" xlink:href="$(INST)/share/basic/Military/script.xlb/" xlink:type="simple" library:link="true" library:readonly="false"/>' \
  "$BASIC_DIR/script.xlc"
echo "[patch-editor] Installed Military macro library"

# ── Impress-specific UI suppressions ───────────────────────────────────────
# Bundle.js is shared across Writer / Calc / Impress, so the autoShowFeedback,
# Help tab, fitWidthZoom, branding-CSS and Pytho-logo patches above already
# apply when an PPTX loads. The Impress-only pieces — slide panel default
# open, the SlideShow / Animations / Transitions tabs that no analyst will
# use, the Calc / Impress per-format icons — get handled here.
#
# Without these patches the analyst opens a PPTX (Threat Overlay, SITEMP,
# MCOO, …) in the LiveEditor and sees: a left rail of slide thumbnails
# (the slide sorter — eats horizontal real estate), Impress-specific
# notebookbar tabs that don't apply to doc editing, the LibreOffice
# default file-type icon instead of the Pytho logo.

# Sidebar default-open is ALREADY stubbed for Impress — the existing
# `initializeSidebar=function` sed up above covers Writer + Impress (the
# bundle has one shared initializeSidebar; only Calc has its own variant
# `calcInitializeSidebar`). Kept the comment block so the next person
# editing this section sees what was considered + rejected.

# Kill Impress's slide-controls panel default-on. (showSlideControls is
# the actual variable name in the bundle, not the showslidesorter /
# showslidepane I initially guessed — confirmed by grepping for
# `show[Ss]lide[a-zA-Z]*=` in bundle.js.)
sed -i 's/showSlideControls=true/showSlideControls=false/g' "$F"

# NOTE: not stripping Slideshow / Animation / MasterPage notebookbar tabs.
# They're standard PowerPoint affordances — if the analyst wants to add a
# slide transition or tweak a master, they should be able to. Hiding them
# is overreach. Leave the ribbon as Impress ships it.

# Replace the Impress file-type icon (x-office-presentation.svg) and the
# Calc file-type icon (x-office-spreadsheet.svg) with the Pytho logo so
# the analyst sees the Pytho brand in the top-left regardless of which
# format they opened. Mirror of the writer x-office-document.svg swap.
if [ -f /pytho-logo.svg ]; then
  cp /pytho-logo.svg "$IMGS/x-office-presentation.svg"
  cp /pytho-logo.svg "$IMGS/x-office-spreadsheet.svg"
  echo "[patch-editor] Replaced impress + calc icons with Pytho logo"
fi
echo "[patch-editor] Impress-specific UI suppressions applied"


# ── Install Pytho Python scripts (CallPythonScript surface) ──────────────
# Collabora restricts CallPythonScript to .py files prepared in advance in
# the canonical share/Scripts/python/ directory. Per docker-compose, our
# scripts get mounted at /pytho-scripts read-only; copy them to the
# canonical share dir at boot so the editor sees them. Restart-cycle = one
# `docker compose up -d --build --force-recreate editor` after editing.
SCRIPTS_DST="/opt/collaboraoffice/share/Scripts/python"
if [ -d /pytho-scripts ]; then
  mkdir -p "$SCRIPTS_DST"
  cp /pytho-scripts/*.py "$SCRIPTS_DST/" 2>/dev/null
  chmod 644 "$SCRIPTS_DST"/*.py 2>/dev/null
  count=$(ls /pytho-scripts/*.py 2>/dev/null | wc -l)
  echo "[patch-editor] Installed $count Pytho Python scripts → $SCRIPTS_DST"
fi

# ── Install Python script provider (REQUIRED for CallPythonScript) ──
# The `collabora/code` base image does NOT bundle the Python script
# provider. Without it the XScriptProvider component is empty and every
# CallPythonScript dispatch fails with:
#   ScriptFrameworkErrorException: invalid attempt to assign an empty
#   interface of type com.sun.star.script.provider.XScriptProvider!
# Install both `collaboraofficebasis-python-script-provider` (registers
# the Python provider with LibreOffice) and `collaboraofficebasis-pyuno`
# (the Python ↔ UNO bridge). Idempotent — dpkg --status check skips the
# expensive apt-get call once installed (image-cache layers retain them
# across container restarts).
if ! dpkg -s collaboraofficebasis-python-script-provider >/dev/null 2>&1 \
    || ! dpkg -s collaboraofficebasis-pyuno >/dev/null 2>&1; then
  if [ -d /pytho-debs ] && ls /pytho-debs/*.deb >/dev/null 2>&1; then
    # Air-gap path. The two debs (pyuno + python-script-provider) live in
    # pytho-app/editor/debs/ and are bind-mounted at /pytho-debs read-only.
    # The previous version of this block called `apt-get install` which
    # silently fails on the airgapped spark (no apt repo reachable), so
    # every CallPythonScript dispatch hit XScriptProvider's
    # "invalid attempt to assign an empty interface" error and the Done-
    # editing flow had to fall back to a 15-45s iframe reload. NEVER
    # regress this to apt-get; dpkg-i-from-disk is the only working path
    # in the deployed environment.
    echo "[patch-editor] Installing Python script provider + pyuno from /pytho-debs (offline)..."
    ARCH="$(dpkg --print-architecture)"
    if ! ls /pytho-debs/collaboraofficebasis-pyuno_*_"$ARCH".deb >/dev/null 2>&1; then
      echo "[patch-editor] WARN: no vendored debs for $ARCH — the Python/UNO macro bridge is ABSENT on this arch (viewer unaffected); vendor ${ARCH} debs to restore it"
      SKIP_PYUNO=1
    fi
    [ -z "$SKIP_PYUNO" ] && \
    dpkg -i /pytho-debs/collaboraofficebasis-pyuno_*_"$ARCH".deb \
            /pytho-debs/collaboraofficebasis-python-script-provider_*_"$ARCH".deb \
            2>&1 | tail -5
  else
    echo "[patch-editor] WARN: /pytho-debs missing — falling back to apt-get (FAILS air-gapped)"
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y collaboraofficebasis-python-script-provider \
                       collaboraofficebasis-pyuno 2>&1 | tail -3
  fi
  # Repopulate the jail systemplate so kit children pick up pyuno.so +
  # pythonscript.py. The deb postinst tries this but can fail silently
  # if coolwsd-systemplate-setup wasn't pre-created at install time.
  coolconfig update-system-template 2>/dev/null || true
  echo "[patch-editor] Python script provider ready"
else
  echo "[patch-editor] Python script provider already installed"
fi


# A unified image applies the patch once during docker build. The
# original entrypoint behavior remains for the standalone deployment.
if [ "${PYTHO_EDITOR_PATCH_ONLY:-0}" = "1" ]; then
  echo "[patch-editor] Build-time patch complete"
  exit 0
fi

# Drop back to cool user and start normally
exec su -s /bin/sh cool -c "exec /start-collabora-online.sh"

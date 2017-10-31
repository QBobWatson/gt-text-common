"use strict";

fs      = require 'fs'
mjAPI   = require 'mathjax-node'
cheerio = require 'cheerio'


################################################################################
# Utility

die = (str, err) ->
    console.log str
    console.log err.toString()
    process.exit 1

# Promise wrapper to read file data
readFile = (fileName, type) ->
    new Promise (resolve, reject) ->
        fs.readFile fileName, type, (err, data) ->
            reject err if err
            resolve data
    .catch (err) -> die "Can't read #{fileName}", err

# Promise wrapper to write file data
writeFile = (fileName, str) ->
    new Promise (resolve, reject) ->
        fs.writeFile fileName, str, (err) ->
            reject err if err
            resolve fileName
    .catch (err) -> die "Can't write #{fileName}", err

# Make temp directory and put 3rd party extensions there
# Have to replace the path name in the files -- very annoying
tmpDir = "#{__dirname}/tmp"
fs.mkdirSync tmpDir unless fs.existsSync tmpDir

makeExtension = (filename) ->
    readFile "#{__dirname}/extensions/#{filename}", 'utf8'
    .then (data) ->
        data = data.replace /{{PATH}}/g, tmpDir
        writeFile "#{tmpDir}/#{filename}", data


################################################################################
# File processing

processFile = (filename, preamble) ->
    css = null
    $ = null

    mjAPI.start()

    mjAPI.typeset
        math:   preamble
        format: 'TeX'
        css:    true
    .catch (errors) ->
        console.log "Error compiling preamble:"
        console.log "-------------------------"
        console.log preamble
        console.log "-------------------------"
        console.log errors.join("\n")
        process.exit 1
    .then (data) ->
        css = data.css
        readFile filename, 'utf8'
    .then (data) ->
        $ = cheerio.load data,
            xml:
                normalizeWhitespace: false
                xmlMode: false

        promises = []
        # Replace math
        $('script[type^="text/x-mathjax"]').each () ->
            if $(this).attr('type') == 'text/x-mathjax-inline'
                format = 'inline-TeX'
            else
                format = 'TeX'
            promise = mjAPI.typeset
                math:   $(this).html()
                format: format
                html:   true
            .then (data) => $(this).replaceWith data.html
            .catch (errors) =>
                console.log "Error compiling MathJax in #{filename}:"
                console.log "------------------------"
                console.log $(this).html()
                console.log "------------------------"
                console.log errors.join("\n")
                process.exit 1
            promises.push promise
            true
        Promise.all promises
    .then () ->
        # Hack to recover font scaling
        css += '.mjx-chtml { font-size: 106%; }\n'
        $("#mathjax-style").text css
        writeFile filename, $.html()
    .then () -> console.log "Wrote #{filename}"


################################################################################
# Main routine

nocss = false
files = process.argv.slice 2
if files[0] == '--no-css'
    nocss = true
    files.shift()
preambleFile = files.shift()

makeExtension 'spalign.js'
.then makeExtension 'bevel.js'
.then () ->
    mjAPI.config
        fontURL: 'static/fonts/HTML-CSS'
        displayErrors: false
        MathJax:
            extensions: ["file://#{__dirname}/tmp/spalign.js",
                         "file://#{__dirname}/tmp/bevel.js"]
            TeX:
                extensions: ["extpfeil.js", "autobold.js",
                             "noUndefined.js", "AMSmath.js", "AMSsymbols.js"]
                # scrolling to fragment identifiers is controlled by other Javascript
                positionToHash: false
                equationNumbers: autoNumber: "none"
                TagSide: "right"
                TagIndent: ".8em"
            CommonHTML:
                scale: 88  # no effect with no js running on the page
                mtextFontInherit: true
    readFile preambleFile, 'utf8'
.then (preamble) ->
    # Process files sequentially
    files.reduce ((promise, file) -> promise.then processFile file, preamble),
        Promise.resolve()

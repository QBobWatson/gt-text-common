(function() {
  "use strict";
  var cheerio, die, files, fs, makeExtension, mjAPI, nocss, preambleFile, processFile, readFile, tmpDir, writeFile;

  fs = require('fs');

  mjAPI = require('mathjax-node');

  cheerio = require('cheerio');

  die = function(str, err) {
    console.log(str);
    console.log(err.toString());
    return process.exit(1);
  };

  readFile = function(fileName, type) {
    return new Promise(function(resolve, reject) {
      return fs.readFile(fileName, type, function(err, data) {
        if (err) {
          reject(err);
        }
        return resolve(data);
      });
    })["catch"](function(err) {
      return die("Can't read " + fileName, err);
    });
  };

  writeFile = function(fileName, str) {
    return new Promise(function(resolve, reject) {
      return fs.writeFile(fileName, str, function(err) {
        if (err) {
          reject(err);
        }
        return resolve(fileName);
      });
    })["catch"](function(err) {
      return die("Can't write " + fileName, err);
    });
  };

  tmpDir = __dirname + "/tmp";

  if (!fs.existsSync(tmpDir)) {
    fs.mkdirSync(tmpDir);
  }

  makeExtension = function(filename) {
    return readFile(__dirname + "/extensions/" + filename, 'utf8').then(function(data) {
      data = data.replace(/{{PATH}}/g, tmpDir);
      return writeFile(tmpDir + "/" + filename, data);
    });
  };

  processFile = function(filename, preamble) {
    var $, css;
    css = null;
    $ = null;
    mjAPI.start();
    return mjAPI.typeset({
      math: preamble,
      format: 'TeX',
      css: true
    })["catch"](function(errors) {
      console.log("Error compiling preamble:");
      console.log("-------------------------");
      console.log(preamble);
      console.log("-------------------------");
      console.log(errors.join("\n"));
      return process.exit(1);
    }).then(function(data) {
      css = data.css;
      return readFile(filename, 'utf8');
    }).then(function(data) {
      var promises;
      $ = cheerio.load(data, {
        xml: {
          normalizeWhitespace: false,
          xmlMode: false
        }
      });
      promises = [];
      $('script[type^="text/x-mathjax"]').each(function() {
        var format, promise;
        if ($(this).attr('type') === 'text/x-mathjax-inline') {
          format = 'inline-TeX';
        } else {
          format = 'TeX';
        }
        promise = mjAPI.typeset({
          math: $(this).html(),
          format: format,
          html: true
        }).then((function(_this) {
          return function(data) {
            return $(_this).replaceWith(data.html);
          };
        })(this))["catch"]((function(_this) {
          return function(errors) {
            console.log("Error compiling MathJax in " + filename + ":");
            console.log("------------------------");
            console.log($(_this).html());
            console.log("------------------------");
            console.log(errors.join("\n"));
            return process.exit(1);
          };
        })(this));
        promises.push(promise);
        return true;
      });
      return Promise.all(promises);
    }).then(function() {
      css += '.mjx-chtml { font-size: 106%; }\n';
      $("#mathjax-style").text(css);
      return writeFile(filename, $.html());
    }).then(function() {
      return console.log("Wrote " + filename);
    });
  };

  nocss = false;

  files = process.argv.slice(2);

  if (files[0] === '--no-css') {
    nocss = true;
    files.shift();
  }

  preambleFile = files.shift();

  makeExtension('spalign.js').then(makeExtension('bevel.js')).then(function() {
    mjAPI.config({
      fontURL: 'static/fonts/HTML-CSS',
      displayErrors: false,
      MathJax: {
        extensions: ["file://" + __dirname + "/tmp/spalign.js", "file://" + __dirname + "/tmp/bevel.js"],
        TeX: {
          extensions: ["extpfeil.js", "autobold.js", "noUndefined.js", "AMSmath.js", "AMSsymbols.js"],
          positionToHash: false,
          equationNumbers: {
            autoNumber: "none"
          },
          TagSide: "right",
          TagIndent: ".8em"
        },
        CommonHTML: {
          scale: 88,
          mtextFontInherit: true
        }
      }
    });
    return readFile(preambleFile, 'utf8');
  }).then(function(preamble) {
    return files.reduce((function(promise, file) {
      return promise.then(processFile(file, preamble));
    }), Promise.resolve());
  });

}).call(this);

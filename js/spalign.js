/*************************************************************
 *
 *  Implements the \spalign{} package for typesetting matrices.
 *
 *  ---------------------------------------------------------------------
 *
 *  Copyright (c) 2017 Joseph Rabinoff
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

MathJax.Extension["TeX/spalign"] = {
  version: "1.0.0"
};

MathJax.Hub.Register.StartupHook("TeX Jax Ready",function () {

    var MML = MathJax.ElementJax.mml;
    var TEX = MathJax.InputJax.TeX;
    var TEXDEF = TEX.Definitions;

    var delims = ['(', ')'];
    var sysdelims = ['\\{', '.'];
    var systabspace = '1pt';

    var readEntry = function(string) {
        var i = 0;
        var ret = '';
        // Skip spaces
        while(string.charAt(i).match(/\s/)) {i++}
        if(i == string.length) {return null}

        while(i < string.length &&
              string.charAt(i) != ',' &&
              string.charAt(i) != ';' &&
              !string.charAt(i).match(/\s/)) {
            switch (string.charAt(i)) {
            case '}':
                TEX.Error(["ExtraCloseMissingOpen",
                           "Extra close brace or missing open brace"]);
                return null;
            case '\\':
                // Parse control sequence
                i++;
                var CS = string.slice(i).match(/^([a-z]+|.) ?/i);
                if (CS) {
                    i += CS[1].length;
                    ret += '\\' + CS[1];
                } else {
                    i++;
                    ret += '\\ ';
                }
                if(ret.charAt(ret.length-1).match(/[a-z]/)) {
                    // Ignore spaces after ordinary control sequence
                    while(string.charAt(i).match(/\s/)) {i++}
                    // Put a space after ordinary control sequences
                    ret += ' ';
                }
                break;
            case '{':
                // Take everything up to matching close brace
                var j = i++, parens = 1;
                while (i < string.length && parens > 0) {
                    switch (string.charAt(i++)) {
                    case '\\':  i++; break;
                    case '{':   parens++; break;
                    case '}':
                        if (--parens == 0) {
                            ret += string.slice(j, i);
                        }
                        break;
                    }
                }
                if (parens > 0) {
                    TEX.Error(["MissingCloseBrace", "Missing close brace"]);
                    return null;
                }
                break;
            default:
                ret += string.charAt(i);
                i++;
                break;
            }
        }
        return [ret, string.slice(i)];
    }

    /*
     * Emulate spalign's retokenizer.
     *
     * We cheat a bit here when retokenizing aligned equations by pre-parsing
     * the internal macros \. \+ \= and surrounding odd columns by {}.
     */
    var retokenize = function(string, aligntab='&', eoltoken='\\\\', syseq=false) {
        var entry, ret = '', tuple, maxcols = 0;
        var row = [];
        while(true) {
            tuple = readEntry(string);
            if(!tuple) {break}
            entry = tuple[0];
            string = tuple[1];
            if(entry) {
                if(syseq) {
                    if(entry === "\\.") {entry = "{}"}
                    else if(entry === "\\+") {entry = "\\mathbin{\\phantom{+}}"}
                    else if(entry === "\\=") {entry = "\\mathbin{\\phantom{=}}"}
                    if(row.length % 2) {
                        entry = "{}" + entry + "{}";
                    }
                }
                row.push(entry);
            }
            if(!string) {break}
            switch(string[0]) {
            case ',':
                string = string.slice(1);
                break;
            case ';':
                string = string.slice(1);
                ret += row.join(aligntab) + eoltoken;
                if(row.length > maxcols) {maxcols = row.length}
                row = [];
                break;
            }
        }
        if (row) {
            ret += row.join(aligntab) + eoltoken;
            if(row.length > maxcols) {maxcols = row.length}
        }
        return [ret, maxcols];
    }


    TEXDEF.Add({
        macros: {
            spaligndelims: 'SpalignSetDelims',
            spalignsysdelims: 'SpalignSetSysDelims',
            spalignsystabspace: 'SpalignSetSysTabSpace',
            spalignarray: 'SpalignArray',
            spalignmat: 'SpalignMat',
            spalignvector: 'SpalignVector',
            spalignaugmatn: ['SpalignAugMat', null],
            spalignaugmat: ['SpalignAugMat', 1],
            spalignaugmathalf: ['SpalignAugMat', 'half'],
            spalignsys: 'SpalignSys',
        }, environment: {
            spaligngen: 'SpalignGen',
            'spaligngen*': 'SpalignGen',
            spaligngensys: 'SpalignGenSys',
            'spaligngensys*': 'SpalignGenSys',
        }}, null, true);

    TEX.Parse.Augment({

        /*
         *  Macros for setting package parameters.  Note that these have global
         *  effect, since MathJax doesn't have a good notion of scoping.  To set
         *  delimiters locally, just set the delimiters back to the default
         *  afterwards.
         */
        SpalignSetDelims: function(name) {
            var open = this.GetArgument(name);
            var close = this.GetArgument(name);
            delims = [open, close];
        },
        SpalignSetSysDelims: function(name) {
            var open = this.GetArgument(name);
            var close = this.GetArgument(name);
            sysdelims = [open, close];
        },
        SpalignSetSysTabSpace: function(name) {
            var spacing = this.GetDimen(name);
            systabspace = spacing;
        },

        /*
         *  General matrix environment for spalign: automatically adds
         *  delimiters.
         */
        SpalignGen: function(begin) {
            var open, close;
            var align = this.GetArgument("\\begin{"+begin.name+"}");
            if(begin.name.charAt(begin.name.length-1) === "*") {
                open = null;
                close = null
            } else if(delims) {
                open = delims[0];
                close = delims[1];
            } else {
                open = '(';
                close = ')';
            }
            return this.Array(begin, open, close, align);
        },

        /*
         *  Implement \spalignarray{}{}
         */
        SpalignArray: function(name) {
            var star = '';
            if(this.GetNext() === '*') {
                star = '*';
                this.i++;
            }
            var align = this.GetArgument(name);
            var arg = this.GetArgument(name);

            var tuple = retokenize(arg);
            var retokenized = tuple[0];
            var envname = "spaligngen" + star;
            var parsestr
                = "\\begin{" + envname + "}{" + align + "}"
                + retokenized
                + "\\end{" + envname + "}";
            this.Push(TEX.Parse(parsestr, this.stack.env).mml());
        },

        /*
         *  Implement \spalignmat[]{}
         */
        SpalignMat: function(name) {
            var star = '';
            if(this.GetNext() === '*') {
                star = '*';
                this.i++;
            }
            var align = this.GetBrackets(name, 'c');
            var arg = this.GetArgument(name);

            var tuple = retokenize(arg);
            var retokenized = tuple[0];
            var maxcols = tuple[1];
            align = Array(maxcols+1).join(align);
            var envname = "spaligngen" + star;
            var parsestr
                = "\\begin{" + envname + "}{" + align + "}"
                + retokenized
                + "\\end{" + envname + "}";
            this.Push(TEX.Parse(parsestr, this.stack.env).mml());
        },

        /*
         *  Implement \spalignvector[]{}
         */
        SpalignVector: function(name) {
            var star = '';
            if(this.GetNext() === '*') {
                star = '*';
                this.i++;
            }
            var align = this.GetBrackets(name, 'c');
            var arg = this.GetArgument(name);

            var tuple = retokenize(arg, '\\\\');
            var retokenized = tuple[0];
            var envname = "spaligngen" + star;
            var parsestr
                = "\\begin{" + envname + "}{" + align + "}"
                + retokenized
                + "\\end{" + envname + "}";
            this.Push(TEX.Parse(parsestr, this.stack.env).mml());
        },

        /*
         *  Implement \spalignaugmatn[]{}{}
         */
        SpalignAugMat: function(name, augmentcol) {
            var star = '';
            if(this.GetNext() === '*') {
                star = '*';
                this.i++;
            }
            var align = this.GetBrackets(name, 'r');
            if(!augmentcol) {augmentcol = parseInt(this.GetArgument(name))}
            var arg = this.GetArgument(name);

            var tuple = retokenize(arg);
            var retokenized = tuple[0];
            var maxcols = tuple[1];
            if(augmentcol === "half") {
                augmentcol = Math.floor(maxcols/2);
            }
            var align2 = Array(maxcols - augmentcol+1).join(align);
            align2 += '|';
            align2 += Array(augmentcol+1).join(align);
            var envname = "spaligngen" + star;
            var parsestr
                = "\\begin{" + envname + "}{" + align2 + "}"
                + retokenized
                + "\\end{" + envname + "}";
            this.Push(TEX.Parse(parsestr, this.stack.env).mml());
        },

        /*
         *  Environment version of \spalignsys; used to create a custom Array
         *  (to get the spacing right).
         */
        SpalignGenSys: function(begin) {
            var open, close;
            var align = this.GetArgument("\\begin{"+begin.name+"}");
            if(begin.name.charAt(begin.name.length-1) === "*") {
                open = null;
                close = null
            } else if(sysdelims) {
                open = sysdelims[0];
                close = sysdelims[1];
            } else {
                open = '\\{';
                close = '.';
            }
            var spacing = '1pt;'
            if(systabspace) {spacing = systabspace}
            return this.Array(begin, open, close, align, spacing);
        },

        /*
         *  Implement \spalignsys{}
         */
        SpalignSys: function(name) {
            var star = '';
            if(this.GetNext() === '*') {
                star = '*';
                this.i++;
            }
            var arg = this.GetArgument(name);

            var tuple = retokenize(arg, '&', '\\\\', true);
            var retokenized = tuple[0];
            var maxcols = tuple[1];
            var i, align = '';
            for(i = 0; i < maxcols; ++i) {
                if(i % 2) {align += 'r'}
                else      {align += 'c'}
            }
            var envname = "spaligngensys" + star;
            var parsestr
                = "\\begin{" + envname + "}{" + align + "}"
                + retokenized
                + "\\end{" + envname + "}";
            this.Push(TEX.Parse(parsestr, this.stack.env).mml());
        },
    });

    MathJax.Hub.Startup.signal.Post("TeX spalign Ready");

});

MathJax.Ajax.loadComplete("[Extra]/spalign.js");

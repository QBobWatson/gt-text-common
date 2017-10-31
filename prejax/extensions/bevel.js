/* support for the sfrac command in MathJax (Beveled fraction) */
/* see: https://github.com/mathjax/MathJax-docs/wiki/Beveled-fraction-like-sfrac,-nicefrac-bfrac */


MathJax.Hub.Register.StartupHook("TeX Jax Ready", function () {
  var MML = MathJax.ElementJax.mml,
      TEX = MathJax.InputJax.TeX;
  TEX.Definitions.macros.sfrac = "myBevelFraction";
  TEX.Parse.Augment({
    myBevelFraction: function (name) {
      var num = this.ParseArg(name),
          den = this.ParseArg(name);
      this.Push(MML.mfrac(num,den).With({bevelled: true}));
    }
  });
});

// {{PATH}} replaced by generator script
MathJax.Ajax.loadComplete("file://{{PATH}}/bevel.js");

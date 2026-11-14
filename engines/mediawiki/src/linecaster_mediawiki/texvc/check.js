// texvc for linecaster-mediawiki (texvc.py): one formula's TeX per line on stdin (a JSON string), one answer per line
// on stdout, {"status": texvc's status ("+" accepted), "output": the formula as texvc writes it, or null}.
const texvc = require("mathoid-texvcjs");
const rl = require("readline").createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  let r;
  try {
    r = texvc.check(JSON.parse(line), { usemhchem: true });
  } catch (e) {
    r = { status: "E" };
  }
  process.stdout.write(JSON.stringify({ status: r.status, output: r.status === "+" ? r.output : null }) + "\n");
});

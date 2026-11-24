# Locale build tools

npm ci --prefix dev/tools
npm run locales --prefix dev/tools
npm run check --prefix dev/tools

English assets are generated from Persian JS/HTML and the reviewed English catalog. Changes to either require regeneration and both language browser suites. Never run translation on arbitrary DOM text or user content. See dev/audit/bilingual-20261124/REPORT.md for validation and release gates.

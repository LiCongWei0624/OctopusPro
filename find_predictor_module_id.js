const fs = require('fs');

global.window = global;
global.addEventListener = function() {};
global.removeEventListener = function() {};
global.window.addEventListener = function() {};
global.document = {
    createElement: function() { return { src: '', appendChild: function() {} }; },
    head: { appendChild: function() {} },
    getElementsByTagName: function() { return [{ appendChild: function() {} }]; },
    createEvent: function() { return { initEvent: function() {} }; },
    addEventListener: function() {},
    body: { offsetHeight: 100 }
};
global.navigator = { userAgent: 'Mozilla/5.0' };
global.sessionStorage = {
    getItem: function() { return null; },
    setItem: function() {}
};
global.localStorage = {
    getItem: function() { return null; },
    setItem: function() {}
};
global.location = { href: 'https://m.leisu.com/', search: '' };

const files = ['3d179aa.js', 'fe66d24.js', '0299bd5.js', 'de74dcb.js'];
files.forEach(f => {
    try {
        const content = fs.readFileSync(f, 'utf-8');
        eval(content);
    } catch(e) {}
});

let webpackRequire = null;
try {
    window.webpackJsonp.push([
        [999999], 
        {
            999999: function(module, exports, __webpack_require__) {
                webpackRequire = __webpack_require__;
            }
        },
        [[999999]]
    ]);
} catch(e) {}

if (webpackRequire) {
    for (let i = 0; i < 3000; i++) {
        try {
            const mod = webpackRequire(i);
            // check if mod exports functions or has keys like Ib, Hb
            if (mod && mod.Jb) { // gen_order_lottery might be Jb or similar
                console.log(`Module ${i} has keys:`, Object.keys(mod).slice(0, 10));
            }
        } catch(e) {}
    }
}

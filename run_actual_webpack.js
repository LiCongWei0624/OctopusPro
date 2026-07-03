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
    } catch(e) {
        console.log(`Error evaluating ${f}:`, e.message);
    }
});

// webpackJsonp is now populated. We need to extract __webpack_require__ (usually webpackJsonp's push returns it or we can intercept it)
// In 3d179aa.js, the webpackJsonp.push handler stores the require function in window.webpackJsonp's custom function, or we can get it from the modules map.
// Let's print the webpackJsonp object to see what it is
console.log("webpackJsonp:", typeof webpackJsonp);

// Actually, in Webpack bootstrap, the push function is overridden.
// Let's inspect window.webpackJsonp:
// If it has been overridden, we can push a dummy chunk to get __webpack_require__!
// Let's do it:
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
} catch(e) {
    console.log("Error pushing dummy chunk:", e.message);
}

if (webpackRequire) {
    console.log("SUCCESSFULLY EXTRACTED __webpack_require__!");
    try {
        const mod2 = webpackRequire(2);
        console.log("Module 2 exports:", typeof mod2);
        console.log("mod2.amoutspring:", mod2.amoutspring);
    } catch(e) {
        console.log("Error requiring module 2:", e.message);
    }
} else {
    console.log("Failed to extract __webpack_require__!");
}

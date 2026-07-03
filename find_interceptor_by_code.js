const fs = require('fs');

const globalModules = {};

global.window = global;
global.webpackJsonp = [];
global.webpackJsonp.push = function(arr) {
    const modules = arr[1];
    if (Array.isArray(modules)) {
        modules.forEach((mod, idx) => {
            if (mod) globalModules[idx] = mod;
        });
    } else if (modules) {
        Object.keys(modules).forEach(key => {
            globalModules[key] = modules[key];
        });
    }
};

const files = ['fe66d24.js', '0299bd5.js', 'de74dcb.js'];
files.forEach(f => {
    try {
        const content = fs.readFileSync(f, 'utf-8');
        eval(content);
    } catch(e) {}
});

console.log("Total registered modules:", Object.keys(globalModules).length);

Object.keys(globalModules).forEach(key => {
    const src = globalModules[key].toString();
    if (src.includes('s.amoutspring')) {
        console.log(`Found s.amoutspring in Module ID: ${key}`);
        console.log(src.slice(0, 1000));
    }
});

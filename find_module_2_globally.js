
const fs = require('fs');

const globalModules = {};

global.window = {
    webpackJsonp: {
        push: function(arr) {
            const chunkIds = arr[0];
            const modules = arr[1];
            console.log(`Push called for chunks: ${chunkIds}`);
            if (Array.isArray(modules)) {
                modules.forEach((mod, idx) => {
                    if (mod) {
                        globalModules[idx] = {
                            source: mod.toString(),
                            chunk: chunkIds
                        };
                    }
                });
            } else if (modules) {
                Object.keys(modules).forEach(key => {
                    globalModules[key] = {
                        source: modules[key].toString(),
                        chunk: chunkIds
                    };
                });
            }
        }
    }
};

const files = ['3d179aa.js', 'fe66d24.js', '0299bd5.js', 'de74dcb.js'];
files.forEach(f => {
    try {
        const content = fs.readFileSync(f, 'utf-8');
        eval(content);
    } catch (e) {
        console.log(`Error evaluating ${f}:`, e.message);
    }
});

console.log('\nChecking keys count in globalModules:', Object.keys(globalModules).length);
for (let target of [2, 164, 201]) {
    if (globalModules[target]) {
        console.log(`\n==================================================`);
        console.log(`FOUND MODULE ${target} in chunk ${globalModules[target].chunk}:`);
        console.log(`==================================================`);
        console.log(globalModules[target].source);
    } else {
        console.log(`\nModule ${target} NOT FOUND in global registry!`);
    }
}

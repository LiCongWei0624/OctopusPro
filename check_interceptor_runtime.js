const fs = require('fs');

const globalModules = {};

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
global.location = { href: 'https://m.leisu.com/', search: '', host: 'm.leisu.com' };

// We override webpackJsonp before loading chunks to register modules without executing entrypoints!
global.webpackJsonp = [];
global.webpackJsonp.push = function(arr) {
    const chunkIds = arr[0];
    const modules = arr[1];
    console.log(`Registered chunk: ${chunkIds}`);
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
    } catch(e) {
        console.log(`Error evaluating ${f}:`, e.stack);
    }
});

// Mock Webpack require function
function webpackRequire(moduleId) {
    if (webpackRequire.cache[moduleId]) {
        return webpackRequire.cache[moduleId].exports;
    }
    const module = webpackRequire.cache[moduleId] = {
        i: moduleId,
        l: false,
        exports: {}
    };
    
    if (!globalModules[moduleId]) {
        throw new Error(`Module ${moduleId} not found in globalModules!`);
    }
    
    globalModules[moduleId].call(module.exports, module, module.exports, webpackRequire);
    module.l = true;
    return module.exports;
}
webpackRequire.cache = {};

// Mock require properties
webpackRequire.d = function(exports, name, getter) {
    Object.defineProperty(exports, name, { enumerable: true, get: getter, configurable: true });
};
webpackRequire.n = function(module) {
    var getter = module && module.__esModule ?
        function() { return module['default']; } :
        function() { return module; };
    webpackRequire.d(getter, 'a', getter);
    return getter;
};
webpackRequire.r = function(exports) {
    Object.defineProperty(exports, '__esModule', { value: true });
};
// Bind Webpack require to global window so modules can find it if needed
global.webpackJsonp.push = function(arr) {
    // just dummy
};

console.log("\nTotal registered modules:", Object.keys(globalModules).length);

try {
    const mod8 = webpackRequire(8);
    
    // Wrap MD5 to print input
    const mod164 = webpackRequire(164);
    const originalMD5 = mod164.b;
    Object.defineProperty(mod164, 'b', {
        get: function() {
            return function(str) {
                console.log("EXACT HASHED STRING (l):", str);
                return originalMD5(str);
            };
        },
        configurable: true
    });
    
    const axiosClient = mod8.b; // exports.b is C
    
    console.log("Axios Client found:", typeof axiosClient);
    
    const handlers = axiosClient.interceptors.request.handlers;
    console.log("Interceptor handlers count:", handlers.length);
    
    const interceptor = handlers[0].fulfilled;
    
    const mockConfig = {
        url: '/v1/web/match/football/match_list',
        headers: {},
        params: { date: '20260629', n: 0 }
    };
    
    interceptor(mockConfig).then(res => {
        console.log("Interceptor ran successfully!");
        console.log("Resulting headers:", res.headers);
        console.log("Resulting Accept header:", res.headers.Accept);
        
        // Decrypt the payload to see what auth_data it has!
        const acceptHeader = res.headers.Accept;
        const encrypted = acceptHeader.split(';;')[1];
        
        const crypto = require('crypto');
        let base64 = encrypted.replace(/-/g, '+').replace(/_/g, '/');
        while (base64.length % 4) {
            base64 += '=';
        }
        const key = Buffer.from('kw@h*8gCIn$8X#df', 'utf8');
        const decipher = crypto.createDecipheriv('aes-128-ecb', key, null);
        let decrypted = decipher.update(base64, 'base64', 'utf8');
        decrypted += decipher.final('utf8');
        
        console.log("Decrypted Accept payload:", decrypted);
    }).catch(err => {
        console.log("Error running interceptor:", err.stack);
    });
    
} catch(e) {
    console.log("Error running module 48080:", e.stack);
}

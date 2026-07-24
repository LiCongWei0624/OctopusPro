const fs = require('fs');
const vm = require('vm');

function extractJSON(str) {
    // renderData may contain JavaScript: var requestInfo = {...};
    // Extract the JSON object part
    const braceMatch = str.match(/\{[\s\S]*\}/);
    if (braceMatch) return braceMatch[0];
    return str;
}

function solveWaf(html) {
    const renderDataMatch = html.match(/<textarea id="renderData"[^>]*>([\s\S]*?)<\/textarea>/);
    if (!renderDataMatch) return null;
    let renderDataStr = renderDataMatch[1];
    // If renderData is JS (var requestInfo = {...};), extract the JSON part
    const jsonStr = extractJSON(renderDataStr);
    let renderDataObj;
    try {
        renderDataObj = JSON.parse(jsonStr);
    } catch (e) {
        // If JSON parsing still fails, try stripping JS prefix
        console.error('renderData JSON parse error, raw:', renderDataStr.substring(0, 100));
        return null;
    }
    
    const wafTextareaMatch = html.match(/<textarea name="aliyunwaf_[^"]+" style="display:none">([\s\S]*?)<\/textarea>/);
    const wafTextareaContent = wafTextareaMatch ? wafTextareaMatch[1] : '';
    const wafTextareaName = html.match(/<textarea name="(aliyunwaf_[^"]+)"/)?.[1] || '';
    
    const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)];
    if (scripts.length < 2) return null;
    const obfuscatedJS = scripts[1][1];

    let cookieValue = null;
    
    const targetUrl = process.argv[2] || 'https://www.leisu.com/guide';
    const mockLocation = {
        href: targetUrl,
        reload: () => {}
    };

    const mockDocument = {
        cookie: '',
        referrer: '',
        location: mockLocation,
        getElementById: (id) => {
            if (id === 'renderData') {
                return { innerHTML: renderDataStr };
            }
            return null;
        },
        getElementsByName: (name) => {
            if (name === wafTextareaName) {
                return [{
                    value: wafTextareaContent,
                    getAttribute: (attr) => attr === 'value' ? wafTextareaContent : null
                }];
            }
            return [];
        }
    };

    const mockNavigator = {
        userAgent: process.argv[3] || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        platform: 'Win32'
    };

    const documentProxy = new Proxy(mockDocument, {
        get(target, prop) {
            if (prop in target) return target[prop];
            return undefined;
        }
    });

    const windowProxy = new Proxy({}, {
        get(target, prop) {
            if (prop === 'document') return documentProxy;
            if (prop === 'location') return mockLocation;
            if (prop === 'navigator') return mockNavigator;
            if (prop === 'window' || prop === 'self' || prop === 'top' || prop === 'parent') return windowProxy;
            if (prop === 'setTimeout') return setTimeout;
            if (prop === 'setInterval') return setInterval;
            if (prop === 'clearTimeout') return clearTimeout;
            if (prop === 'clearInterval') return clearInterval;
            if (prop === 'renderData') return renderDataObj;
            if (prop === 'arg1') return renderDataObj.l1.slice(10, 60);
            if (prop === 'setCookie') {
                return (e, r) => {
                    cookieValue = r;
                };
            }
            if (prop === 'reload') {
                return (e) => {
                    cookieValue = e;
                };
            }
            return target[prop];
        }
    });

    const sandbox = {
        window: windowProxy,
        document: documentProxy,
        location: mockLocation,
        navigator: mockNavigator,
        setTimeout: setTimeout,
        setInterval: setInterval,
        clearTimeout: clearTimeout,
        clearInterval: clearInterval,
        renderData: renderDataObj,
        arg1: renderDataObj.l1.slice(10, 60),
        setCookie: (e, r) => {
            cookieValue = r;
        },
        reload: (e) => {
            cookieValue = e;
        }
    };

    try {
        vm.runInNewContext(obfuscatedJS, sandbox, { timeout: 1000 });
        return cookieValue;
    } catch (e) {
        console.error("VM Execution Error:", e);
        return null;
    }
}

// Read from file or stdin
let inputData = '';
const lastArg = process.argv[process.argv.length - 1];
if (lastArg && lastArg.endsWith('.html') && fs.existsSync(lastArg)) {
    try {
        inputData = fs.readFileSync(lastArg, 'utf8');
        runSolver(inputData);
    } catch(err) {
        console.log(JSON.stringify({ success: false, error: 'Read file error: ' + err.message }));
    }
} else {
    process.stdin.on('data', chunk => {
        inputData += chunk;
    });
    process.stdin.on('end', () => {
        runSolver(inputData);
    });
}

function runSolver(html) {
    try {
        const result = solveWaf(html);
        if (result) {
            console.log(JSON.stringify({ success: true, cookie: result }));
        } else {
            console.log(JSON.stringify({ success: false, error: 'Could not solve WAF' }));
        }
    } catch (err) {
        console.log(JSON.stringify({ success: false, error: err.message }));
    }
}

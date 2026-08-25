// Self-resolving Protomaps planet build — no pinned date, no restarts.
//
// Protomaps publishes daily planet builds at
// https://build.protomaps.com/YYYYMMDD.pmtiles and prunes old ones from
// the CDN after a few weeks. A date pinned in tileserver-config.json
// therefore rots: a fresh tileserver start 404s and crash-loops, and a
// long-running one breaks mid-flight when its build is pruned.
//
// Fix, at request time: tileserver-config.json points at the STABLE
// internal URL http://tilecache:8080/planet.pmtiles. On the first range
// request this handler probes dated builds — starting at tomorrow (UTC)
// and counting down — and locks onto the newest one that answers 200.
// The resolved date lives in an njs shared dict, so every subsequent
// range request proxies straight through with zero probe overhead. If
// the CDN later prunes the resolved build (upstream 404 mid-flight),
// nginx lands on the stale handler, the date is re-probed, and the same
// request is retried against the new build — the tileserver never sees
// the rotation.
//
// Wired in nginx.conf:
//   js_shared_dict_zone zone=pmtiles:32k;
//   js_set $pmtiles_date pmtiles.date;
//   location = /planet.pmtiles   { js_content pmtiles.route; }
//   location /_pmtiles/fetch     { internal; proxy_pass https://build.protomaps.com/$pmtiles_date.pmtiles; ... }
//   location /_pmtiles/stale     { internal; js_content pmtiles.stale; }

const UPSTREAM = 'https://build.protomaps.com';
// How many days to walk back from tomorrow before giving up. Builds are
// published daily and pruned after weeks, so anything close to 60 means
// the CDN itself is gone.
const MAX_PROBE_DAYS = 60;

function yyyymmdd(d) {
    return d.toISOString().slice(0, 10).replace(/-/g, '');
}

async function probe(r) {
    const start = new Date(Date.now() + 24 * 3600 * 1000); // tomorrow UTC
    for (let i = 0; i < MAX_PROBE_DAYS; i++) {
        const d = yyyymmdd(new Date(start.getTime() - i * 24 * 3600 * 1000));
        try {
            const resp = await ngx.fetch(`${UPSTREAM}/${d}.pmtiles`, { method: 'HEAD' });
            if (resp.status === 200) {
                r.log(`pmtiles resolver: locked onto build ${d}`);
                return d;
            }
        } catch (e) {
            r.error(`pmtiles resolver: probe ${d} failed: ${e}`);
        }
    }
    return null;
}

function date(r) {
    return ngx.shared.pmtiles.get('date') || '';
}

async function route(r) {
    if (!ngx.shared.pmtiles.get('date')) {
        const d = await probe(r);
        if (!d) {
            r.return(502, 'pmtiles resolver: no live Protomaps build found\n');
            return;
        }
        ngx.shared.pmtiles.set('date', d);
    }
    r.internalRedirect('/_pmtiles/fetch');
}

// Upstream 404 mid-flight: the resolved build was pruned. Re-probe, then
// serve THIS request directly via a buffered ranged fetch against the
// fresh build (r.internalRedirect does not re-enter the proxy from an
// error_page context — verified with a mock CDN, the client got the 404).
// Buffering is fine here: pmtiles range reads are small (KBs–MBs) and
// this path runs only at the prune boundary; every subsequent request
// takes the fast proxy path with the re-locked date.
async function stale(r) {
    const dead = ngx.shared.pmtiles.get('date') || '(unset)';
    ngx.shared.pmtiles.delete('date');
    const d = await probe(r);
    if (!d || d === dead) {
        r.return(502, `pmtiles resolver: build ${dead} pruned and no newer build found\n`);
        return;
    }
    ngx.shared.pmtiles.set('date', d);
    r.log(`pmtiles resolver: build ${dead} pruned, re-locked onto ${d}`);
    const headers = {};
    if (r.headersIn['Range']) {
        headers['Range'] = r.headersIn['Range'];
    }
    const resp = await ngx.fetch(`${UPSTREAM}/${d}.pmtiles`, { headers: headers });
    const body = await resp.arrayBuffer();
    ['Content-Range', 'Content-Type', 'ETag', 'Accept-Ranges'].forEach((h) => {
        const v = resp.headers.get(h);
        if (v) {
            r.headersOut[h] = v;
        }
    });
    r.return(resp.status, body);
}

export default { route, stale, date };

const {test} = require('node:test');
const assert = require('node:assert/strict');
const {compareCells} = require('../gold_digger/table.js');
test('sort numbers, money and missing values in both directions', () => {
    assert.deepEqual(['10','2','—','100'].sort((a,b)=>compareCells(a,b,1)), ['2','10','100','—']);
    assert.deepEqual(['10','2','—','100'].sort((a,b)=>compareCells(a,b,-1)), ['100','10','2','—']);
    assert(compareCells('−1 po 00 pa 00 pc','0 po 99 pa 99 pc',1)<0);
    assert(compareCells('1 000 po 00 pa 00 pc','99 po 00 pa 00 pc',1)>0);
    assert(compareCells('1.25','1.9',1)<0);
});
test('click a header twice to reorder existing rows without replacing links', () => {
    function element(text='') {
        return {textContent:text, attrs:{}, append(child){this.firstChild=child;},
            setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},removeAttribute(k){delete this.attrs[k];},
            addEventListener(event,fn){this[event]=fn;}};
    }
    const header=element('Rentabilité (%)');
    const rows=['10','2','—'].map(text=>({cells:[{textContent:text}],link:{href:'https://www.wowhead.com/forever/fr/item=2320'}}));
    const body={rows:[...rows],append(...sorted){this.rows=sorted;}};
    global.document={querySelector(){return {querySelectorAll(){return [header];},tBodies:[body]};},createElement(){return element();}};
    delete require.cache[require.resolve('../gold_digger/table.js')];
    try {
        require('../gold_digger/table.js');
        header.firstChild.click();
        assert.deepEqual(body.rows,[rows[1],rows[0],rows[2]]);
        assert.equal(header.attrs['aria-sort'],'ascending');
        header.firstChild.click();
        assert.deepEqual(body.rows,[rows[0],rows[1],rows[2]]);
        assert.equal(header.attrs['aria-sort'],'descending');
        assert.equal(body.rows[0].link,rows[0].link);
    } finally {delete global.document;}
});

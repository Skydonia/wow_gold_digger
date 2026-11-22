function sortValue(text) {
    const value = text.trim();
    if (!value || value === '—') return null;
    const money = value.match(/^([−-]?)([\d ]+) po (\d+) pa (\d+) pc$/);
    if (money) return (money[1] ? -1 : 1) * (Number(money[2].replaceAll(' ', '')) * 10000 + Number(money[3]) * 100 + Number(money[4]));
    if (/^[−-]?\d+(?:[.,]\d+)?$/.test(value)) return Number(value.replace('−', '-').replace(',', '.'));
    return value;
}
function compareCells(left, right, direction) {
    const a = sortValue(left), b = sortValue(right);
    if (a === null) return b === null ? 0 : 1;
    if (b === null) return -1;
    return direction * (typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'fr', {numeric: true, sensitivity: 'base'}));
}
if (typeof document !== 'undefined') {
    const table = document.querySelector('table');
    const headers = [...table.querySelectorAll('th')];
    headers.forEach((header, index) => {
        const button = document.createElement('button');
        const label = header.textContent;
        button.textContent = label + ' ↕';
        button.title = 'Trier par ' + label;
        header.textContent = '';
        header.append(button);
        button.addEventListener('click', () => {
            const direction = header.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
            headers.forEach(h => {
                h.removeAttribute('aria-sort');
                h.firstChild.textContent = h.firstChild.title.replace('Trier par ', '') + ' ↕';
            });
            header.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
            button.textContent = label + (direction === 1 ? ' ↑' : ' ↓');
            const rows = [...table.tBodies[0].rows];
            rows.sort((a,b) => compareCells(a.cells[index].textContent,b.cells[index].textContent,direction));
            table.tBodies[0].append(...rows);
        });
    });
}
if (typeof module !== 'undefined') module.exports = {sortValue, compareCells};

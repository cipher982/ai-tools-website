const search = document.getElementById("search");

search.addEventListener("input", (e) => {
    const term = e.target.value.toLowerCase();
    const cards = document.querySelectorAll(".tool-card");
    const categories = document.querySelectorAll(".category");

    cards.forEach(card => {
        const searchText = card.dataset.search;
        const visible = searchText.includes(term);
        card.style.display = visible ? "" : "none";
    });

    categories.forEach(category => {
        const visibleCards = category.querySelectorAll(".tool-card[style='']").length;
        category.style.display = visibleCards ? "" : "none";
    });
}); 
document.addEventListener("DOMContentLoaded", () => {
    const search = document.getElementById("search");
    
    if (search) {
        search.addEventListener("input", (e) => {
            const term = e.target.value.toLowerCase();
            
            document.querySelectorAll(".tool-card").forEach(card => {
                const searchText = card.dataset.search || "";
                card.style.display = searchText.includes(term) ? "block" : "none";
            });

            // Hide empty categories
            document.querySelectorAll(".category").forEach(category => {
                const hasVisibleCards = Array.from(category.getElementsByClassName("tool-card"))
                    .some(card => card.style.display !== "none");
                category.style.display = hasVisibleCards ? "block" : "none";
            });
        });
    }
}); 
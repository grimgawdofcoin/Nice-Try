/* ============ BONE JUNGLE — cart (localStorage demo cart) ============ */
const CART_KEY = "bonejungle_cart";

function readCart(){
  try{ return JSON.parse(localStorage.getItem(CART_KEY)) || []; }
  catch(e){ return []; }
}
function writeCart(items){
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  renderCartCount();
  renderDrawer();
}
function addToCart(product){
  const items = readCart();
  const existing = items.find(i => i.id === product.id);
  if(existing){ existing.qty += 1; }
  else { items.push({ ...product, qty: 1 }); }
  writeCart(items);
}
function changeQty(id, delta){
  let items = readCart();
  items = items.map(i => i.id === id ? { ...i, qty: Math.max(1, i.qty + delta) } : i);
  writeCart(items);
}
function removeItem(id){
  writeCart(readCart().filter(i => i.id !== id));
}
function cartTotal(){
  return readCart().reduce((sum,i) => sum + i.price * i.qty, 0);
}
function cartCount(){
  return readCart().reduce((sum,i) => sum + i.qty, 0);
}
function renderCartCount(){
  document.querySelectorAll("[data-cart-count]").forEach(el => {
    const n = cartCount();
    el.textContent = n;
    el.hidden = n === 0;
  });
}
function renderDrawer(){
  const list = document.getElementById("drawerItems");
  const totalEl = document.getElementById("drawerTotal");
  if(!list) return;
  const items = readCart();
  if(items.length === 0){
    list.innerHTML = `<div class="drawer-empty">Your bag is empty.<br>Go feed it something feral.</div>`;
  } else {
    list.innerHTML = items.map(i => `
      <div class="drawer-item">
        <div class="g">${i.glyph}</div>
        <div class="d">
          <div class="n">${i.name}</div>
          <div class="m">$${i.price} &middot; ${i.size || "One Size"}</div>
          <div class="qty">
            <button aria-label="decrease" onclick="changeQty('${i.id}',-1)">&minus;</button>
            <span>${i.qty}</span>
            <button aria-label="increase" onclick="changeQty('${i.id}',1)">+</button>
          </div>
        </div>
        <button class="rm" onclick="removeItem('${i.id}')">Remove</button>
      </div>
    `).join("");
  }
  if(totalEl) totalEl.textContent = "$" + cartTotal().toFixed(2);
}
function openDrawer(){
  document.getElementById("cartOverlay").classList.add("open");
  document.getElementById("cartDrawer").classList.add("open");
}
function closeDrawer(){
  document.getElementById("cartOverlay").classList.remove("open");
  document.getElementById("cartDrawer").classList.remove("open");
}
document.addEventListener("DOMContentLoaded", () => {
  renderCartCount();
  renderDrawer();
  const openBtn = document.getElementById("cartBtn");
  if(openBtn) openBtn.addEventListener("click", openDrawer);
  const closeBtn = document.getElementById("cartClose");
  if(closeBtn) closeBtn.addEventListener("click", closeDrawer);
  const overlay = document.getElementById("cartOverlay");
  if(overlay) overlay.addEventListener("click", closeDrawer);

  const menuToggle = document.getElementById("menuToggle");
  const navLinks = document.getElementById("navLinks");
  if(menuToggle && navLinks){
    menuToggle.addEventListener("click", () => {
      const isOpen = navLinks.style.display === "flex";
      navLinks.style.display = isOpen ? "none" : "flex";
    });
  }
});

const form=document.querySelector("#crawl-form");
const button=document.querySelector("#search-button");
const systemStatus=document.querySelector("#system-status");
const loadingPanel=document.querySelector("#loading-panel");
const resultsArea=document.querySelector("#results-area");
const listingsGrid=document.querySelector("#listings-grid");
const listingsEmpty=document.querySelector("#listings-empty");
const sourceStatusGrid=document.querySelector("#source-status-grid");
const sortButton=document.querySelector("#sort-ppm2");

let currentListings=[];
let ascending=true;

const money=new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL",maximumFractionDigits:0});
const money2=new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL",maximumFractionDigits:2});

function escapeHtml(value){
  return String(value??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
}

function label(source){
  return {zap:"ZAP",vivareal:"Viva Real",imovelweb:"Imovelweb",chavesnamao:"Chaves na Mão",olx:"OLX"}[source]||source;
}

function setLoading(active,city=""){
  button.disabled=active;
  button.classList.toggle("is-loading",active);
  loadingPanel.classList.toggle("hidden",!active);
  if(active){
    resultsArea.classList.add("hidden");
    systemStatus.textContent=`Varredura em ${city} em andamento`;
  }else if(systemStatus.textContent.includes("andamento")){
    systemStatus.textContent="Varredura concluída";
  }
}

function renderSummary(data){
  document.querySelector("#metric-listings").textContent=data.summary.listings??0;
  document.querySelector("#metric-price").textContent=data.summary.median_price?money.format(data.summary.median_price):"—";
  document.querySelector("#metric-ppm2").textContent=data.summary.median_price_per_m2?money2.format(data.summary.median_price_per_m2):"—";
  document.querySelector("#metric-sources").textContent=data.summary.sources_with_results??0;
  document.querySelector("#result-location").textContent=`${data.query.city}/${data.query.state}`;
}

function renderSources(sources){
  sourceStatusGrid.innerHTML=sources.map(source=>{
    const state=source.successful>0?"ok":source.failed>0?"bad":"warn";
    return `<article class="source-card">
      <div class="source-card-top"><span class="source-name">${escapeHtml(label(source.source))}</span><span class="source-state ${state}"></span></div>
      <div class="source-stats">
        <div><span>Descobertos</span><strong>${source.discovered_urls}</strong></div>
        <div><span>Válidos</span><strong>${source.successful}</strong></div>
        <div><span>Falhas</span><strong>${source.failed}</strong></div>
        <div><span>Robots</span><strong>${source.skipped_by_robots}</strong></div>
      </div>
    </article>`;
  }).join("");
}

function renderListings(listings){
  currentListings=listings;
  listingsEmpty.classList.toggle("hidden",listings.length>0);
  listingsGrid.innerHTML=listings.map(item=>{
    const title=item.title||"Terreno anunciado";
    const location=item.address||item.neighborhood||`${item.city}/${item.state}`;
    return `<article class="listing-card">
      <span class="listing-source">${escapeHtml(label(item.source))}</span>
      <h3>${escapeHtml(title)}</h3>
      <div class="listing-location">${escapeHtml(location)}</div>
      <div class="listing-values">
        <div><span>Preço</span><strong>${item.price?money.format(item.price):"—"}</strong></div>
        <div><span>Área</span><strong>${item.area_m2?`${Number(item.area_m2).toLocaleString("pt-BR")} m²`:"—"}</strong></div>
        <div><span>Preço/m²</span><strong>${item.price_per_m2?money2.format(item.price_per_m2):"—"}</strong></div>
        <div><span>Bairro</span><strong>${escapeHtml(item.neighborhood||"—")}</strong></div>
      </div>
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Abrir anúncio ↗</a>
    </article>`;
  }).join("");
}

function showError(message){
  resultsArea.classList.remove("hidden");
  sourceStatusGrid.innerHTML="";
  listingsEmpty.classList.add("hidden");
  listingsGrid.innerHTML=`<div class="error-card">${escapeHtml(message)}</div>`;
}

form.addEventListener("submit",async event=>{
  event.preventDefault();
  const city=document.querySelector("#city").value.trim();
  const state=document.querySelector("#state").value;
  const limit=Number(document.querySelector("#limit").value);
  const pages=Number(document.querySelector("#pages").value);
  const sources=[...document.querySelectorAll('input[name="source"]:checked')].map(input=>input.value);

  if(!sources.length){alert("Selecione pelo menos uma fonte.");return;}
  setLoading(true,city);

  try{
    const response=await fetch("/api/crawl",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({city,state,limit,pages,sources})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||"Não foi possível executar a varredura.");
    renderSummary(data);
    renderSources(data.sources||[]);
    renderListings(data.listings||[]);
    resultsArea.classList.remove("hidden");
    resultsArea.scrollIntoView({behavior:"smooth",block:"start"});
  }catch(error){
    systemStatus.textContent="Falha na varredura";
    showError(error.message);
  }finally{
    setLoading(false,city);
  }
});

sortButton.addEventListener("click",()=>{
  if(!currentListings.length)return;
  const sorted=[...currentListings].sort((a,b)=>{
    const av=a.price_per_m2??Number.POSITIVE_INFINITY;
    const bv=b.price_per_m2??Number.POSITIVE_INFINITY;
    return ascending?av-bv:bv-av;
  });
  ascending=!ascending;
  sortButton.textContent=ascending?"Ordenar por R$/m²":"Inverter ordem R$/m²";
  renderListings(sorted);
});

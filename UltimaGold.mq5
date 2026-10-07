#property strict
#property version "0.20"
#include <Trade/Trade.mqh>
// Research prototype. Attach one instance only, to your broker's gold chart.
input bool SignalsOnly=true;
input bool AllowRealAccount=false;
input double MaxRiskEUR=10.0;
input double MaxMarginEUR=10.0;
input double MaxExperimentLossEUR=50.0;
input int MaxExperimentEntries=5;
input double CostReservePercent=25.0;
input ulong Magic=26010752; // This identifies the entire five-trade experiment.
CTrade trade;
int fast=INVALID_HANDLE,slow=INVALID_HANDLE,entryMA=INVALID_HANDLE,atr=INVALID_HANDLE;
datetime lastBar=0;
string fxSymbol="";
bool inverseFX=false;
void Status(string s) { Comment("Ultima Gold v0.20\n",s); Print(s); }
bool EURRate(double &rate) {
 if(AccountInfoString(ACCOUNT_CURRENCY)=="EUR") { rate=1; return true; }
 MqlTick q;
 if(fxSymbol=="" || !SymbolInfoTick(fxSymbol,q) || q.bid<=0 || q.ask<q.bid || TimeCurrent()-q.time>300 || q.time>TimeCurrent()+60) return false;
 // Conservative conversion of EUR spending caps into the account currency.
 rate=inverseFX?1.0/q.ask:q.bid;
 return MathIsValidNumber(rate) && rate>0;
}
bool ReadValue(int h,int shift,double &v) {
 double b[1]; if(CopyBuffer(h,0,shift,1,b)!=1) return false;
 v=b[0]; return MathIsValidNumber(v) && v!=EMPTY_VALUE && v>0;
}
int OnInit() {
 if(MaxRiskEUR<=0 || MaxRiskEUR>10 || MaxMarginEUR<=0 || MaxMarginEUR>10 || MaxExperimentLossEUR<=0 || MaxExperimentLossEUR>50 ||
    MaxExperimentEntries<1 || MaxExperimentEntries>5 || CostReservePercent<20 || CostReservePercent>=100)
    return INIT_PARAMETERS_INCORRECT;
 string currency=AccountInfoString(ACCOUNT_CURRENCY);
 if(currency!="EUR") {
    for(int i=0;i<SymbolsTotal(false);i++) {
       string name=SymbolName(i,false);
       string b=SymbolInfoString(name,SYMBOL_CURRENCY_BASE),p=SymbolInfoString(name,SYMBOL_CURRENCY_PROFIT);
       if((b=="EUR" && p==currency) || (b==currency && p=="EUR")) {
          if(SymbolSelect(name,true)) { fxSymbol=name; inverseFX=(p=="EUR"); break; }
       }
    }
    if(fxSymbol=="") { Print("No EUR/account-currency conversion available; refusing to assume EUR=USD or cents."); return INIT_FAILED; }
 }
 string base=SymbolInfoString(_Symbol,SYMBOL_CURRENCY_BASE);
 if(base!="XAU" || SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT)!="USD") {
    Print("Use an XAU/USD gold chart; unknown symbol specifications rejected."); return INIT_FAILED;
 }
 fast=iMA(_Symbol,PERIOD_M30,20,0,MODE_EMA,PRICE_CLOSE);
 slow=iMA(_Symbol,PERIOD_M30,50,0,MODE_EMA,PRICE_CLOSE);
 entryMA=iMA(_Symbol,PERIOD_M5,20,0,MODE_EMA,PRICE_CLOSE);
 atr=iATR(_Symbol,PERIOD_M5,14);
 if(fast==INVALID_HANDLE || slow==INVALID_HANDLE || entryMA==INVALID_HANDLE || atr==INVALID_HANDLE) return INIT_FAILED;
 trade.SetExpertMagicNumber(Magic); trade.SetDeviationInPoints(10);
 trade.SetAsyncMode(false);
 if(!trade.SetTypeFillingBySymbol(_Symbol)) return INIT_FAILED;
 lastBar=iTime(_Symbol,PERIOD_M5,0);
 Status("Ready; SignalsOnly="+(string)SignalsOnly+"; real account permission="+(string)AllowRealAccount);
 return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {
 IndicatorRelease(fast); IndicatorRelease(slow); IndicatorRelease(entryMA); IndicatorRelease(atr); Comment("");
}
bool ExperimentGuard(double rate,double &remaining) {
 // Full account history for this Magic: neither a new day nor restart resets it.
 if(!HistorySelect(0,TimeCurrent())) return false;
 double losses=0; int entries=0; datetime latest=0; ulong seenOrders[],ownedPositions[];
 // Include manual exits of positions originally opened by this experiment.
 for(int i=0;i<HistoryDealsTotal();i++) {
    ulong t=HistoryDealGetTicket(i); if(t==0) return false;
    if((ulong)HistoryDealGetInteger(t,DEAL_MAGIC)!=Magic || HistoryDealGetString(t,DEAL_SYMBOL)!=_Symbol) continue;
    long en=HistoryDealGetInteger(t,DEAL_ENTRY);
    if(en!=DEAL_ENTRY_IN && en!=DEAL_ENTRY_INOUT) continue;
    ulong pos=(ulong)HistoryDealGetInteger(t,DEAL_POSITION_ID); if(pos==0) return false;
    int n=ArraySize(ownedPositions);
    if(ArrayResize(ownedPositions,n+1)!=n+1) return false;
    ownedPositions[n]=pos;
 }
 for(int i=0;i<HistoryDealsTotal();i++) {
    ulong t=HistoryDealGetTicket(i); if(t==0) return false;
    if(HistoryDealGetString(t,DEAL_SYMBOL)!=_Symbol) continue;
    ulong pos=(ulong)HistoryDealGetInteger(t,DEAL_POSITION_ID);
    bool owned=false;
    for(int j=0;j<ArraySize(ownedPositions);j++) if(ownedPositions[j]==pos) { owned=true; break; }
    if(!owned) continue;
    double p=HistoryDealGetDouble(t,DEAL_PROFIT)+HistoryDealGetDouble(t,DEAL_COMMISSION)+
       HistoryDealGetDouble(t,DEAL_SWAP)+HistoryDealGetDouble(t,DEAL_FEE);
    // Conservatively count negative deal amounts; wins never refill the budget.
    losses+=MathMax(0,-p);
    datetime tm=(datetime)HistoryDealGetInteger(t,DEAL_TIME); if(tm>latest) latest=tm;
    long en=HistoryDealGetInteger(t,DEAL_ENTRY);
    if((en==DEAL_ENTRY_IN || en==DEAL_ENTRY_INOUT) && (ulong)HistoryDealGetInteger(t,DEAL_MAGIC)==Magic) {
       ulong order=(ulong)HistoryDealGetInteger(t,DEAL_ORDER); if(order==0) return false;
       bool found=false;
       for(int j=0;j<ArraySize(seenOrders);j++) if(seenOrders[j]==order) { found=true; break; }
       if(!found) { if(ArrayResize(seenOrders,entries+1)!=entries+1) return false; seenOrders[entries++]=order; }
    }
 }
 double balance=AccountInfoDouble(ACCOUNT_BALANCE);
 if(balance<=0) return false;
 losses+=MathMax(0,balance-AccountInfoDouble(ACCOUNT_EQUITY));
 // Non-EUR historical losses use the CURRENT rate; not an exact EUR ledger.
 remaining=MaxExperimentLossEUR*rate-losses;
 return remaining>0 && entries<MaxExperimentEntries && (latest==0 || TimeCurrent()-latest>=1800);
}
void OnTick() {
 datetime bar=iTime(_Symbol,PERIOD_M5,0);
 if(bar==0 || bar==lastBar) return;
 // One attempt per closed bar; no retries after uncertain server responses.
 lastBar=bar;
 if(Bars(_Symbol,PERIOD_M30)<100 || Bars(_Symbol,PERIOD_M5)<100) { Status("Waiting for history"); return; }
 if(PositionsTotal()>0 || OrdersTotal()>0) { Status("Account already has exposure; no new trade"); return; }
 double rate=0;
 if(!EURRate(rate)) { Status("Waiting for valid EUR conversion quote"); return; }
 double remaining=0;
 if(!ExperimentGuard(rate,remaining)) { Status("Five-trade experiment limit, loss limit, cooldown or unavailable history"); return; }
 double f,s,e1,e2,a;
 if(!ReadValue(fast,1,f)||!ReadValue(slow,1,s)||!ReadValue(entryMA,1,e1)||!ReadValue(entryMA,2,e2)||!ReadValue(atr,1,a)) return;
 double c1=iClose(_Symbol,PERIOD_M5,1),c2=iClose(_Symbol,PERIOD_M5,2);
 if(c1<=0 || c2<=0) return;
 bool buy=f>s && c2<=e2 && c1>e1;
 bool sell=f<s && c2>=e2 && c1<e1;
 if(!buy && !sell) { Status("No closed-candle signal"); return; }
 MqlTick q; if(!SymbolInfoTick(_Symbol,q) || q.ask<=q.bid || q.bid<=0 || TimeCurrent()-q.time>15) return;
 double spread=q.ask-q.bid;
 if(spread>a*0.10) { Status("Spread too large relative to ATR"); return; }
 double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
 double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
 double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
 if(tick<=0 || minimum<=0 || step<=0 || maximum<minimum) return;
 double price=buy?q.ask:q.bid;
 double distance=MathMax(2*a,(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2)*_Point+spread);
 double sl=buy?MathFloor((price-distance)/tick)*tick:MathCeil((price+distance)/tick)*tick;
 double tp=buy?MathCeil((price+2*(price-sl))/tick)*tick:MathFloor((price-2*(sl-price))/tick)*tick;
 sl=NormalizeDouble(sl,_Digits); tp=NormalizeDouble(tp,_Digits);
 if(sl<=0 || tp<=0) return;
 ENUM_ORDER_TYPE type=buy?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
 double loss=0;
 if(!OrderCalcProfit(type,_Symbol,minimum,price,sl,loss) || loss>=0) { Status("Risk calculation failed"); return; }
 double budget=MathMin(MaxRiskEUR*rate,remaining);
 double priceBudget=budget*(1-CostReservePercent/100);
 double minMargin=0;
 if(!OrderCalcMargin(type,_Symbol,minimum,price,minMargin) || minMargin<=0) { Status("Margin calculation failed"); return; }
 double free=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
 // Leave enough equity outside initial margin for the entire planned risk budget.
 double marginCap=MathMin(MaxMarginEUR*rate,free-budget);
 if(marginCap<=0) { Status("Insufficient free margin plus loss buffer"); return; }
 double raw=priceBudget/(-loss)*minimum;
 raw=MathMin(raw,marginCap/minMargin*minimum);
 double volume=NormalizeDouble(MathFloor(MathMin(raw,maximum)/step)*step,8);
 if(volume<minimum) { Status("SKIP: minimum gold order exceeds risk budget"); return; }
 if(!OrderCalcProfit(type,_Symbol,volume,price,sl,loss) || loss>=0 || -loss>priceBudget+0.000001) return;
 double margin=0;
 if(!OrderCalcMargin(type,_Symbol,volume,price,margin) || margin<=0 || margin>marginCap+0.000001) {
    Status("SKIP: insufficient margin buffer"); return;
 }
 Status(StringFormat("%s %.8f lots; estimated price risk %.2f %s; SL %.*f TP %.*f",buy?"BUY":"SELL",volume,-loss,
    AccountInfoString(ACCOUNT_CURRENCY),_Digits,sl,_Digits,tp));
 if(SignalsOnly) return;
 if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO && !MQLInfoInteger(MQL_TESTER) && !AllowRealAccount) {
    Status("Real-account orders disabled"); return;
 }
 if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_EXPERT)) return;
 bool sent=buy?trade.Buy(volume,_Symbol,price,sl,tp,"UltimaGold"):trade.Sell(volume,_Symbol,price,sl,tp,"UltimaGold");
 Print("Request result: ",sent," / ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
 // Server-attached SL/TP. Never open a fallback order without stops.
}
